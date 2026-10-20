from time import sleep
from inspect import signature
import logging
import numpy as np
import json
import os
import time

from drivers.procedure_file_driver import ProcedureFile
from objects.toolhead import Toolhead
from objects.hotplate import Hotplate
from objects.gripper import Gripper
from objects.infeed import Infeed
from objects.pippete import PipetteHandler
from objects.vial_carousel import VialCarousel
from objects.tip_matrix import TipMatrix
from objects.tip_matrix import SlideMatrix

from drivers.camera_driver import Camera
from drivers.spincoater_driver import SpinCoater
from drivers.spectrometer_driver import Spectrometer
from drivers.procedure_file_driver import ProcedureFile
from services.image_processing import ImageProcessor
from services.data_processor import plot_spectra, save_all_to_csv
from drivers.a_star_driver import AStarPlanner


def _get_aruco_calibration_file_path() -> str:
    return os.path.normpath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "calibration_data",
            "aruco_calibrations.json",
        )
    )

class MoveRegistry():
    

    def __init__(self, dispatcher):
        self.logger = logging.getLogger("Main Logger")
        
        self.dispatcher = dispatcher
        self.toolhead = dispatcher.toolhead
        # Keep a reference to the low-level control board for emergency control
        try:
            self.control_board = dispatcher.control_board
        except Exception:
            self.control_board = None
        
        self.infeed = dispatcher.infeed
        self.pipette_handler = dispatcher.pipette_handler
        self.spin_coater = dispatcher.spin_coater
        self.camera = dispatcher.camera
        self.gripper = dispatcher.gripper
        self.hotplate = dispatcher.hotplate
        self.vial_carousel = dispatcher.vial_carousel
        self.spectrometer = dispatcher.spectrometer
        self.spectrometer_frame = None
        self.tip_matrix = dispatcher.tip_matrix
        self.slide_matrix = SlideMatrix()
        
        ImageProcessor.set_detector()

        self.move_dict = {
            "example_move": self.example_move,
            
            "log": self.log,
            "wait": self.wait,
            "home": self.home,
            "aruco_home": self.aruco_home,
            
            "move_toolhead": self.move_toolhead,
            "soft_limit_axis_move": self.soft_limit_axis_move,
            "move_to_location": self.move_to_location,
            
            "set_temperature": self.set_temperature,
            "wait_for_temperature": self.wait_for_temperature,
            
            "align_gripper": self.align_gripper,
            "set_finger_angle": self.set_finger_angle,
            "set_gripper_angle": self.set_gripper_angle,
            "open_gripper": self.open_gripper,
            "close_gripper": self.close_gripper,
            
            
            "add_spin_coater_step": self.add_spin_coater_step,
            "run_spin_coater": self.run_spin_coater,
            
            "set_infeed_angle": self.set_infeed_angle,
            "open_infeed": self.open_infeed,
            "close_infeed": self.close_infeed,

            "set_actuator": self.set_actuator,
            "set_pipette": self.set_pipette,
            "put_away_pipette": self.put_away_pipette,
            "set_eject_angle": self.set_eject_angle,
            "set_vial": self.set_vial,
            "extract_from_vial": self.extract_from_vial,
            "dispense": self.dispense,
            #"replace_tip": self.replace_tip,
            "mix_fluid": self.mix_fluid,
            "eject_tip": self.eject_tip,
            "set_grab_angle": self.set_grab_angle,
            
            "measure_spectrum": self.measure_spectrum,
            "automated_measurement": self.automated_measurement,
            
            "put_0": self.put_0,
            "put_1": self.put_1,
            "set_0": self.set_0,
            "set_1": self.set_1,
        }
        
        
        # procedure coordination info
        self.locations = []
        self.vial = 0
        
    def validate_moves(self, moves: list) -> bool:
        """Validates a list of moves by checking if the move exists in the MoveRegistry
    .
        Also checks if the number of args is correct
        ### Args:
            moves (list):
        ### Returns:
            bool: returns True if all moves are valid, False otherwise
        """
        valid = True

        if not moves:
            self.logger.error("No moves found")
            return False

        for index, move in enumerate(moves):
            func_name = move[0]
            func_args = move[1:]

            if func_name not in self.move_dict:
                self.logger.error(f"Function #{index},{func_name} not found in MoveRegistry")
                valid = False
            
            func = self.move_dict[func_name]
            try:
                sig = signature(func)
                sig.bind(*func_args)
            except TypeError as e:
                self.logger.error(f"Function #{index}, \"{func_name}\" has incorrect arguments: {e}")  
                valid = False

        return valid

    
    def validate_location(self, location: str):
        self.locations = ProcedureFile().Open("persistant/locations.yml")
        location_names = []
        for loc in self.locations:
            location_names.append(loc[0])
            self.logger.debug(loc[0])
            
        if location not in location_names:
            raise ValueError(f"Location name {location} not found")
        
# --------- GENERAL MOVES --------

    def home(self):
        """ Reset the machine"""
        self.toolhead.home()
        self.pipette_handler.home()
        self.vial_carousel.home()
        
        self.tip_matrix.refill_tips()
        self.slide_matrix.refill_slides()
        self.open_gripper()

        
    def kill(self):
        """Emergency stop for all hardware controlled by the MoveRegistry.

        Attempts to stop motion immediately and unblock any waiting operations.
        """
        self.logger.error("MoveRegistry: Emergency kill invoked")
        try:
            if self.dispatcher and hasattr(self.dispatcher, 'notify_emergency_stop'):
                self.dispatcher.notify_emergency_stop()
        except Exception as e:
            self.logger.exception(f"Error while notifying emergency stop listeners: {e}")
        # Control board
        try:
            if self.control_board:
                self.control_board.kill()
        except Exception as e:
            self.logger.exception(f"Error while killing control board: {e}")

        # Spin coater
        try:
            if self.spin_coater:
                self.spin_coater.stop()
                self.spin_coater.clear_steps()
        except Exception as e:
            self.logger.exception(f"Error while stopping spin coater: {e}")

        # Gripper: move to a safe/open position rather than detaching servos so
        # future operations can resume without requiring a manual reattach.
        try:
            if self.gripper:
                try:
                    self.gripper.set_finger_angle(60)
                    # set a safe arm angle if method available
                    if hasattr(self.gripper, 'set_arm_angle'):
                        self.gripper.set_arm_angle(90)
                except Exception:
                    # If servo control isn't available, ignore
                    pass
        except Exception as e:
            self.logger.exception(f"Error while setting gripper to safe state: {e}")

        # Pipette handler: attempt a safe stop if available
        try:
            if self.pipette_handler and hasattr(self.pipette_handler, 'kill'):
                self.pipette_handler.kill()
        except Exception as e:
            self.logger.exception(f"Error while killing pipette handler: {e}")

        # Ensure control board waiting loops are unblocked
        try:
            if self.control_board and hasattr(self.control_board, 'received_ok'):
                self.control_board.received_ok.set()
        except Exception:
            pass

        # Unblock spin coater run/wait logic
        try:
            if self.spin_coater and hasattr(self.spin_coater, 'done'):
                self.spin_coater.done.set()
        except Exception:
            pass
        
    def log(self, message: str):
        """ Log the specified message"""
        self.logger.info(message)

    def wait(self, wait_time_seconds: int):
        """ Wait for the specified amount of time"""
        self.logger.info(f"Waiting for {wait_time_seconds} seconds")
        sleep(wait_time_seconds)
        
    def super_move(self, file_name: str):
        """ Runs a file as a single move"""
        try:
            super_move = ProcedureFile().Open(f"persistant/{file_name}.yml")
            moves = super_move["Procedure"]
        except Exception as e:
            self.logger.error(f"Error while running supermove {file_name}: {e}")
        try:
            for i, move in enumerate(moves):
                self.logger.debug(f"Executing sub-move {i}")
                func_name = move[0]
                func_args = move[1:]
                
                self.move_dict[func_name](*func_args)
        except Exception as e:
            self.logger.error(f"Error while running sub-move: {e}")
            
    def example_move(self, value_1: int, value_2: float, value_3: str):
        return
    #  --------- HOTPLATE MOVES --------
    def set_temperature(self, temperature_c: int):
        if not self.hotplate or not self.hotplate.is_connected():
            raise Exception("Hotplate not connected")
        self.hotplate.set_temperature(temperature_c)
    
    def wait_for_temperature(self, target_temperature: int, threshold: int):
        timeout_s = 600
        while abs(self.hotplate.current_temperature_c - target_temperature) > threshold:
            sleep(1)
            timeout_s -= 1
            if timeout_s == 0:
                raise Exception("Hotplate failed to reach temperature in under 600 seconds. Try a larger threshold?")

    # --------- TOOLHEAD MOVES --------
    def move_toolhead(self, x: float, y: float, z: float, relative: int):
        """Move the toolhead to the specified coordinates (absolute or relative)"""
        self.logger.info(f"move_toolhead: x={x}, y={y}, z={z}, relative={relative}")
        rrelative = False
        if relative >= 1:
            rrelative = True
        # Ensure control board is available before attempting moves
        if not getattr(self, 'control_board', None) or not self.control_board.is_connected():
            raise Exception("Control board not connected")

        # Use per-axis moves for reliability
        self.toolhead.move_to(x=x, y=y, z=z, relative=rrelative, feedrate=1000)

    def _load_persistent_obstacles(self):
        pf = ProcedureFile()
        obstacle_paths = [
            'persistant/obstacles.yml',
            'persistant/obstacles',
            os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'persistant', 'obstacles.yml')),
            os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'persistant', 'obstacles')),
        ]

        for obstacle_path in obstacle_paths:
            obstacles = pf.Open(obstacle_path)
            if obstacles:
                return obstacles

        return []

    def _get_obstacle_bounds(self, entry):
        if isinstance(entry, dict):
            name = str(entry.get('name') or '')
            x1 = float(entry.get('x1', 0)); y1 = float(entry.get('y1', 0)); z1 = float(entry.get('z1', 0))
            x2 = float(entry.get('x2', x1)); y2 = float(entry.get('y2', y1)); z2 = float(entry.get('z2', z1))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 7:
            name = str(entry[0])
            x1 = float(entry[1]); y1 = float(entry[2]); z1 = float(entry[3])
            x2 = float(entry[4]); y2 = float(entry[5]); z2 = float(entry[6])
        else:
            raise ValueError("Unsupported obstacle format")

        return {
            'name': name,
            'xmin': min(x1, x2),
            'xmax': max(x1, x2),
            'ymin': min(y1, y2),
            'ymax': max(y1, y2),
            'zmin': min(z1, z2),
            'zmax': max(z1, z2),
        }

    def _target_obstacle_hit(self, target_x: float, target_y: float, target_z: float, obstacles):
        for entry in obstacles or []:
            try:
                ob = self._get_obstacle_bounds(entry)
            except Exception:
                continue

            if (
                ob['xmin'] <= target_x <= ob['xmax']
                and ob['ymin'] <= target_y <= ob['ymax']
                and ob['zmin'] <= target_z <= ob['zmax']
            ):
                return ob['name'] or 'unnamed obstacle'
        return None

    def _xy_segment_hits_obstacle(self, start_x: float, start_y: float, end_x: float, end_y: float, travel_z: float, obstacles, sample_step_mm: float = 2.0):
        dx = float(end_x) - float(start_x)
        dy = float(end_y) - float(start_y)
        segment_length = max(abs(dx), abs(dy))
        samples = max(1, int(segment_length / max(float(sample_step_mm), 0.5)))

        for sample_index in range(samples + 1):
            t = sample_index / samples
            sample_x = float(start_x) + (dx * t)
            sample_y = float(start_y) + (dy * t)
            hit_obstacle = self._target_obstacle_hit(sample_x, sample_y, travel_z, obstacles)
            if hit_obstacle is not None:
                return hit_obstacle
        return None

    def _clamp_z_to_obstacles(self, target_x: float, target_y: float, requested_z: float, z_clearance_mm: float = 0.0) -> float:
        """Clamp requested Z so destination does not descend into an obstacle volume."""
        min_allowed_z = None

        for entry in self._load_persistent_obstacles():
            try:
                if isinstance(entry, dict):
                    x1 = float(entry.get('x1', 0)); y1 = float(entry.get('y1', 0)); z1 = float(entry.get('z1', 0))
                    x2 = float(entry.get('x2', x1)); y2 = float(entry.get('y2', y1)); z2 = float(entry.get('z2', z1))
                elif isinstance(entry, (list, tuple)) and len(entry) >= 7:
                    x1 = float(entry[1]); y1 = float(entry[2]); z1 = float(entry[3])
                    x2 = float(entry[4]); y2 = float(entry[5]); z2 = float(entry[6])
                else:
                    continue

                xmin, xmax = min(x1, x2), max(x1, x2)
                ymin, ymax = min(y1, y2), max(y1, y2)
                top_z = max(z1, z2)

                if xmin <= target_x <= xmax and ymin <= target_y <= ymax:
                    candidate_min_z = top_z + float(z_clearance_mm)
                    if min_allowed_z is None or candidate_min_z > min_allowed_z:
                        min_allowed_z = candidate_min_z
            except Exception:
                continue

        if min_allowed_z is None:
            return float(requested_z)

        clamped_z = max(float(requested_z), float(min_allowed_z))
        if clamped_z != float(requested_z):
            self.logger.warning(
                "Requested Z %.3f at X=%.3f, Y=%.3f intersects a persistent obstacle; clamping to %.3f",
                float(requested_z),
                float(target_x),
                float(target_y),
                float(clamped_z),
            )
        return clamped_z
        
    def soft_limit_axis_move(self, x: float, y: float, z: float, relative: int):
        """Move to a target while avoiding obstacles listed in persistant/obstacles.yml.

        This performs a coarse A* plan in XY (using `AStarPlanner`) and follows
        the returned waypoints while keeping Z at a safe height until the XY
        travel is complete.
        """
        self.logger.info(f"soft_limit_axis_move: x={x}, y={y}, z={z}, relative={relative}")

        if not getattr(self, 'toolhead', None):
            raise Exception("Toolhead not available for soft_limit_axis_move")

        # fetch current position
        try:
            cx = float(self.toolhead.get_position('X') or 0)
            cy = float(self.toolhead.get_position('Y') or 0)
            cz = float(self.toolhead.get_position('Z') or 0)
        except Exception:
            raise Exception("Unable to read current toolhead position")

        # compute absolute target
        try:
            if int(relative) >= 1:
                tx = cx + float(x)
                ty = cy + float(y)
                tz = cz + float(z)
            else:
                tx = float(x)
                ty = float(y)
                tz = float(z)
        except Exception as e:
            raise ValueError(f"Invalid target coordinates: {e}")

        # load obstacles
        obstacles = self._load_persistent_obstacles()

        # Do not start any movement if the requested target point is inside
        # or exactly on obstacle boundaries.
        hit_obstacle = self._target_obstacle_hit(tx, ty, tz, obstacles)
        if hit_obstacle is not None:
            raise ValueError(
                f"soft_limit_axis_move target ({tx}, {ty}, {tz}) intersects obstacle '{hit_obstacle}'. Move blocked."
            )

        SAFE_Z = 200
        xy_travel_z = max(float(cz), float(SAFE_Z))

        planner = AStarPlanner()
        path = None
        try:
            path = planner.plan((cx, cy, cz), (tx, ty, tz), raw_obstacles=obstacles, travel_z=xy_travel_z)
        except Exception as e:
            if obstacles:
                raise RuntimeError(f"soft_limit_axis_move: path planning failed with obstacles present: {e}")
            self.logger.debug(f"soft_limit_axis_move: planning failed without obstacles: {e}")
            path = None

        if obstacles and (not path or len(path) < 2):
            raise RuntimeError("soft_limit_axis_move: no collision-free path found; move blocked")

        # Move to safe Z before XY travel
        try:
            # only raise if below the XY travel Z to reduce unnecessary moves
            if cz < xy_travel_z:
                self.toolhead.move_axis("Z", xy_travel_z)
        except Exception as e:
            self.logger.exception(f"soft_limit_axis_move: failed to raise to SAFE_Z: {e}")

        # Follow planned XY path or fallback direct move
        try:
            if path and len(path) >= 2:
                # path contains start and goal; skip first (current)
                previous_x = cx
                previous_y = cy
                for px, py in path[1:]:
                    hit_obstacle = self._xy_segment_hits_obstacle(previous_x, previous_y, px, py, xy_travel_z, obstacles)
                    if hit_obstacle is not None:
                        raise RuntimeError(
                            f"soft_limit_axis_move: planned XY segment intersects obstacle '{hit_obstacle}'; move blocked"
                        )
                    self.toolhead.move_to(x=px, y=py, relative=False, feedrate=800, coordinated=True)
                    previous_x = px
                    previous_y = py
            else:
                # No obstacles: direct XY move
                self.logger.info("soft_limit_axis_move: no obstacles loaded, performing direct XY move")
                self.toolhead.move_to(x=tx, y=ty, relative=False, feedrate=1000)
        except Exception as e:
            self.logger.exception(f"soft_limit_axis_move: XY movement failed: {e}")
            raise

        # Move to requested Z at the end
        try:
            self.toolhead.move_axis("Z", tz)
        except Exception as e:
            self.logger.exception(f"soft_limit_axis_move: final Z move failed: {e}")
            raise
        
    def aruco_home(self):
        """Verify gantry using saved ArUco calibrations and move to set location
        """
        # Config
        calibration_file = _get_aruco_calibration_file_path()
        scan_timeout_s = 3.0
        rescan_timeout_s = 1.5
        scan_warmup_s = 0.35
        post_move_settle_s = 0.35
        stable_rescan_attempts = 3
        min_detections_per_marker = 4
        span_threshold_m = 0.012
        tolerance_mm = 4.0
        max_iterations = 25
        jacobian_probe_mm = 1.0
        jacobian_rescan_timeout_s = 1.0
        jacobian_rescan_attempts = 2
        jacobian_refresh_interval = 3
        max_xy_step_mm = 4.0
        max_z_step_mm = 2.0

        # Basic checks
        if not getattr(self, 'camera', None) or not self.camera.is_connected():
            self.logger.warning("aruco_home: camera not connected")
            return

        if not getattr(self, 'control_board', None):
            raise Exception("Control board not available for aruco_home")

        if not getattr(self, 'toolhead', None):
            raise Exception("Toolhead not available for aruco_home")

        # Load saved calibrations
        try:
            if not os.path.exists(calibration_file):
                self.logger.info("aruco_home: no saved calibrations found")
                return

            with open(calibration_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    self.logger.warning("Calibration file is empty")
                    return
                saved = json.loads(content)
                if not isinstance(saved, dict):
                    self.logger.warning("aruco_home: calibration file is not a JSON object")
                    return
                saved = {int(marker_id): data for marker_id, data in saved.items()}
        except Exception as e:
            self.logger.exception(f"aruco_home: failed to load calibration file: {e}")
            return

        # Helper: perform a short scan and aggregate detections
        def scan_for_markers(timeout_s: float, warmup_s: float = 0.0):
            warmup_end = time.time() + max(0.0, warmup_s)
            while time.time() < warmup_end:
                self.camera.get_frame()
                sleep(0.02)

            end_t = time.time() + timeout_s
            detections = {}
            while time.time() < end_t:
                frame = self.camera.get_frame()
                if frame is None:
                    sleep(0.02)
                    continue
                try:
                    result = getattr(self.dispatcher, 'aruco_detector', None).detect_markers(frame)
                except Exception as e:
                    self.logger.debug(f"aruco_home: detector error: {e}")
                    sleep(0.02)
                    continue

                for m in result.get('markers', []):
                    mid = int(m['id'])
                    pos = m['position']
                    detections.setdefault(mid, []).append(pos)

                # small sleep to yield
                sleep(0.01)

            # Filter and aggregate stable positions only
            avg = {}
            stats = {}
            for mid, pts in detections.items():
                if len(pts) < min_detections_per_marker:
                    self.logger.debug(f"aruco_home: marker {mid} seen only {len(pts)} times during scan; skipping")
                    continue

                xs = np.array([p['x'] for p in pts], dtype=float)
                ys = np.array([p['y'] for p in pts], dtype=float)
                zs = np.array([p['z'] for p in pts], dtype=float)
                span_x = float(xs.max() - xs.min())
                span_y = float(ys.max() - ys.min())
                span_z = float(zs.max() - zs.min())
                stats[mid] = {
                    'count': len(pts),
                    'span_x': span_x,
                    'span_y': span_y,
                    'span_z': span_z,
                }

                if span_x > span_threshold_m or span_y > span_threshold_m or span_z > span_threshold_m:
                    self.logger.debug(
                        f"aruco_home: marker {mid} detections too spread (m): "
                        f"x={span_x:.4f} y={span_y:.4f} z={span_z:.4f}; rescanning"
                    )
                    continue

                avg[mid] = {
                    'x': float(np.median(xs)),
                    'y': float(np.median(ys)),
                    'z': float(np.median(zs)),
                }
            return avg, stats

        def scan_for_stable_marker(marker_id: int, timeout_s: float, attempts: int, warmup_s: float):
            last_stats = None
            for attempt in range(1, attempts + 1):
                detected_positions, detected_stats = scan_for_markers(timeout_s, warmup_s=warmup_s)
                last_stats = detected_stats
                rel_pos = detected_positions.get(marker_id)
                if rel_pos is not None:
                    stats = detected_stats.get(marker_id, {})
                    self.logger.debug(
                        f"aruco_home: stable scan for marker {marker_id} succeeded on pass {attempt}/{attempts} "
                        f"with {stats.get('count', 0)} detections"
                    )
                    return rel_pos, last_stats

                if marker_id in detected_stats:
                    stats = detected_stats[marker_id]
                    self.logger.debug(
                        f"aruco_home: marker {marker_id} still unstable on pass {attempt}/{attempts}; "
                        f"count={stats.get('count', 0)} spans(m) x={stats.get('span_x', 0.0):.4f} "
                        f"y={stats.get('span_y', 0.0):.4f} z={stats.get('span_z', 0.0):.4f}"
                    )
                else:
                    self.logger.debug(f"aruco_home: marker {marker_id} not yet stable on pass {attempt}/{attempts}")
            return None, last_stats

        def compute_step_mm(error_mm: float) -> float:
            magnitude = abs(error_mm)
            if magnitude > 25.0:
                step_limit = 2.5
            elif magnitude > 10.0:
                step_limit = 1.5
            elif magnitude > 4.0:
                step_limit = 0.75
            else:
                step_limit = 0.4
            return max(-step_limit, min(step_limit, error_mm))

        # Initial scan
        detected, detected_stats = scan_for_markers(scan_timeout_s, warmup_s=scan_warmup_s)
        if not detected:
            self.logger.info("aruco_home: no markers detected")
            return

        # Find first detected marker that exists in saved calibrations
        matched_id = None
        for mid in detected.keys():
            if mid in saved:
                matched_id = mid
                break

        if matched_id is None:
            self.logger.info("aruco_home: no detected markers match saved calibrations")
            return

        saved_entry = saved[matched_id]
        saved_rel = saved_entry.get('verification_average')
        if not saved_rel:
            relative_positions = saved_entry.get('relative_positions') or []
            if relative_positions:
                saved_rel = relative_positions[0]
        if not saved_rel:
            self.logger.warning(f"aruco_home: saved calibration for {matched_id} missing relative marker pose")
            return

        def rel_to_mm_vector(rel_pos: dict) -> np.ndarray:
            return np.array([
                float(rel_pos['x']) * 1000.0,
                float(rel_pos['y']) * 1000.0,
                float(rel_pos['z']) * 1000.0,
            ], dtype=float)

        def vector_to_rel_dict(vector: np.ndarray) -> dict:
            return {
                'x': float(vector[0]) / 1000.0,
                'y': float(vector[1]) / 1000.0,
                'z': float(vector[2]) / 1000.0,
            }

        def scan_for_stable_marker_vector(marker_id: int, timeout_s: float, attempts: int, warmup_s: float):
            rel_pos, stats = scan_for_stable_marker(marker_id, timeout_s, attempts, warmup_s)
            if rel_pos is None:
                return None, stats
            return rel_to_mm_vector(rel_pos), stats

        def estimate_local_jacobian(current_rel_mm: np.ndarray):
            axis_moves = (
                ('X', np.array([jacobian_probe_mm, 0.0, 0.0], dtype=float)),
                ('Y', np.array([0.0, jacobian_probe_mm, 0.0], dtype=float)),
                ('Z', np.array([0.0, 0.0, jacobian_probe_mm], dtype=float)),
            )
            jacobian = np.zeros((3, 3), dtype=float)

            for column_index, (axis_name, probe_vector) in enumerate(axis_moves):
                try:
                    self.logger.debug(f"aruco_home: probing local Jacobian with +{jacobian_probe_mm:.2f}mm on {axis_name}")
                    self.move_toolhead(float(probe_vector[0]), float(probe_vector[1]), float(probe_vector[2]), 1)
                except Exception as e:
                    self.logger.exception(f"aruco_home: failed to probe {axis_name} axis for Jacobian: {e}")
                    if self.control_board and hasattr(self.control_board, 'is_killed') and self.control_board.is_killed():
                        raise
                    return None, None

                sleep(post_move_settle_s)
                probe_rel_mm, _ = scan_for_stable_marker_vector(
                    matched_id,
                    timeout_s=jacobian_rescan_timeout_s,
                    attempts=jacobian_rescan_attempts,
                    warmup_s=scan_warmup_s,
                )

                try:
                    self.move_toolhead(float(-probe_vector[0]), float(-probe_vector[1]), float(-probe_vector[2]), 1)
                except Exception as e:
                    self.logger.exception(f"aruco_home: failed to return from {axis_name} Jacobian probe: {e}")
                    if self.control_board and hasattr(self.control_board, 'is_killed') and self.control_board.is_killed():
                        raise
                    return None, None

                sleep(post_move_settle_s)

                if probe_rel_mm is None:
                    self.logger.warning(f"aruco_home: marker unstable during {axis_name} Jacobian probe")
                    return None, None

                jacobian[:, column_index] = (probe_rel_mm - current_rel_mm) / jacobian_probe_mm

            centered_rel_mm, _ = scan_for_stable_marker_vector(
                matched_id,
                timeout_s=jacobian_rescan_timeout_s,
                attempts=jacobian_rescan_attempts,
                warmup_s=scan_warmup_s,
            )
            if centered_rel_mm is None:
                self.logger.warning("aruco_home: marker unstable after Jacobian probe return")
                return None, None

            rank = int(np.linalg.matrix_rank(jacobian))
            if rank < 3:
                self.logger.warning(f"aruco_home: local Jacobian is rank-deficient (rank={rank})")
                return None, None

            self.logger.debug(f"aruco_home: local Jacobian(mm_rel/mm_gantry) = {jacobian.tolist()}")
            return jacobian, centered_rel_mm

        target_rel_mm = rel_to_mm_vector(saved_rel)
        current_rel_mm = rel_to_mm_vector(detected[matched_id])
        jacobian = None

        # iterative alignment loop
        iteration = 0
        while iteration < max_iterations:
            iteration += 1

            desired_rel_change_mm = target_rel_mm - current_rel_mm
            err_x = float(desired_rel_change_mm[0])
            err_y = float(desired_rel_change_mm[1])
            err_z = float(desired_rel_change_mm[2])

            self.logger.info(f"aruco_home: Iter {iteration} Marker {matched_id} err(mm) x={err_x:.3f} y={err_y:.3f} z={err_z:.3f}")

            # Check tolerance
            if abs(err_x) <= tolerance_mm and abs(err_y) <= tolerance_mm and abs(err_z) <= tolerance_mm:
                self.logger.info("aruco_home: marker aligned within tolerance")
                return

            if jacobian is None or iteration == 1 or ((iteration - 1) % jacobian_refresh_interval == 0):
                jacobian, current_rel_mm = estimate_local_jacobian(current_rel_mm)
                if jacobian is None or current_rel_mm is None:
                    self.logger.warning("aruco_home: failed to estimate local camera-to-gantry Jacobian")
                    return
                desired_rel_change_mm = target_rel_mm - current_rel_mm
                err_x = float(desired_rel_change_mm[0])
                err_y = float(desired_rel_change_mm[1])
                err_z = float(desired_rel_change_mm[2])
                self.logger.info(
                    f"aruco_home: refreshed Jacobian; err(mm) x={err_x:.3f} y={err_y:.3f} z={err_z:.3f}"
                )

                if abs(err_x) <= tolerance_mm and abs(err_y) <= tolerance_mm and abs(err_z) <= tolerance_mm:
                    self.logger.info("aruco_home: marker aligned within tolerance")
                    return

            try:
                gantry_step_mm, _, _, _ = np.linalg.lstsq(jacobian, desired_rel_change_mm, rcond=None)
            except Exception as e:
                self.logger.exception(f"aruco_home: failed to solve Jacobian correction: {e}")
                return

            gantry_step_mm = np.asarray(gantry_step_mm, dtype=float)
            gantry_step_mm[0] = np.clip(gantry_step_mm[0], -max_xy_step_mm, max_xy_step_mm)
            gantry_step_mm[1] = np.clip(gantry_step_mm[1], -max_xy_step_mm, max_xy_step_mm)
            gantry_step_mm[2] = np.clip(gantry_step_mm[2], -max_z_step_mm, max_z_step_mm)

            step_x = float(gantry_step_mm[0])
            step_y = float(gantry_step_mm[1])
            step_z = float(gantry_step_mm[2])

            # If steps are negligibly small but still outside tolerance, break
            if abs(step_x) < 0.001 and abs(step_y) < 0.001 and abs(step_z) < 0.001:
                self.logger.warning("aruco_home: required step below threshold but still out of tolerance; aborting")
                return

            # Perform relative move
            try:
                self.logger.debug(f"aruco_home: moving relative x={step_x} y={step_y} z={step_z}")
                # move_toolhead expects relative as integer >=1
                self.move_toolhead(step_x, step_y, step_z, 1)
            except Exception as e:
                self.logger.exception(f"aruco_home: failed to perform relative move: {e}")
                if self.control_board and hasattr(self.control_board, 'is_killed') and self.control_board.is_killed():
                    raise
                return

            # allow motion settle
            sleep(post_move_settle_s)

            # Rescan to update relative position after exposure/pose settles.
            rel, _ = scan_for_stable_marker(
                matched_id,
                timeout_s=rescan_timeout_s,
                attempts=stable_rescan_attempts,
                warmup_s=scan_warmup_s,
            )
            if not rel:
                self.logger.warning("aruco_home: marker remained unstable after move, aborting")
                return

            current_rel_mm = rel_to_mm_vector(rel)

        self.logger.warning("aruco_home: max iterations reached without alignment")
        
    def move_to_location(self, destination: str):
        self.validate_location(destination)

        for location in self.locations:
            if destination == location[0]:
                
                x = float(location[1])
                y = float(location[2])
                z = self._clamp_z_to_obstacles(x, y, float(location[3]))
                
                self.toolhead.move_axis("Z", 142)
                sleep(1)
                self.toolhead.move_to(x=x, y=y, relative=0, feedrate=1000)
                sleep(1)
                self.toolhead.move_axis("Z", z)
                sleep(1)
                
                break
         
    # --------- SPIN COATER MOVES --------
    def add_spin_coater_step(self, rpm: int, spin_time_seconds: int):
        """ Command the spincoater to spin at a specified speed for a specified time"""
        
        self.spin_coater.add_step(rpm, spin_time_seconds)
        
    def run_spin_coater(self):
        if not self.spin_coater or not self.spin_coater.is_connected():
            raise Exception("Spin coater not connected")
        self.spin_coater.run(wait_to_finish=True)
    
    # --------- GRIPPER MOVES --------
    def open_gripper(self):
        self.gripper.set_finger_angle(60)
        
    def close_gripper(self):
        self.gripper.set_finger_angle(28)
    
    def set_gripper_angle(self, angle: int):
        self.gripper.set_arm_angle(angle)
        
    def set_finger_angle(self, angle:int):
        self.gripper.set_finger_angle(angle)
    
    def align_gripper(self):
        frame = self.camera.get_frame()
        
        angle0 = None
        angle1 = None
        try_count = 5
        while(angle0 is None or angle1 is None) or abs(angle1-angle0) > 5:
            self.logger.debug("Getting first angle")
            frame = self.camera.get_frame()
            
            angle0 = ImageProcessor.get_marker_angles(image=frame, marker_id=7)
            if angle0 is not None:
                angle0 = angle0 % 90
            
            self.logger.info(f"Got Angle0: {angle0}")
            sleep(1)
            self.logger.debug("Getting second angle")
            frame = self.camera.get_frame()
            angle1 = ImageProcessor.get_marker_angles(image=frame, marker_id=7)
            if angle1 is not None:
                angle1 = angle1 % 90 
            self.logger.debug(f"Got Angle1: {angle1}")
            sleep(1)
            
            try_count -= 1
            
            if try_count == 0:
                raise ValueError("Angle could not be found")
            
        
            
        self.logger.info(int(angle0))
        
        angle0 = (90-angle0) + 27 # from 25
        self.gripper.set_arm_angle(int(angle0))
        
    def grab_new_slide(self):
        self.open_gripper()
        self.move_to_location("slide matrix")
        x_offset, y_offset = self.slide_matrix.get_slide_offset(slide_num=self.slide_matrix.slides_taken)
        self.toolhead.move_axis("X", -x_offset, relative=True)
        self.toolhead.move_axis("Y", -y_offset, relative=True)
        self.toolhead.move_axis("Z", 13)
        self.close_gripper()
        self.toolhead.move_axis("Z", 200)
        self.slide_matrix.take_slide()
        
    # -------- PIPPETE MOVES --------
    def set_actuator(self, position: float):
        self.pipette_handler.set_actuator_position(position)
    
    def replace_tip(self):
        # raise machine to avoid collisions
        self.toolhead.move_axis("Z", 200)
        
        self.move_to_location("tip dropoff")
        self.eject_tip()
        self.move_to_location("tip matrix") #603.2, 193.5, 105

        next_tip_num = self.tip_matrix.tips_taken
        x_offset, y_offset = self.tip_matrix.get_tip_offset()
        self.toolhead.move_axis("X", -x_offset, relative=True)
        self.toolhead.move_axis("Y", -y_offset, relative=True)
        
        self.toolhead.move_axis("Z", 97.5)
        self.toolhead.move_axis("Z", 200)
            
    def extract_from_vial(self, vial_num: int, volume_ul: int):
        vial_draw_height = 82 #distance required for pipette to dip into vial
    
            
        
        self.toolhead.move_axis("Z", 200)
        self.move_to_location("vial carousel")
        self.vial_carousel.set_vial(vial_num)
        self.toolhead.move_axis("Z", vial_draw_height)
        self.pipette_handler.dispense_all(3)
        self.pipette_handler.draw_ul(volume_ul)
        self.toolhead.move_axis("Z", 200)
                
    def mix_fluid(self, source_vial_1: int, amount_1: int, source_vial_2: int, amount_2: int, destination_vial: int):
        vial_draw_height = 82
        

        # raise machine to avoid collisions
        self.toolhead.move_axis("Z", 200)
        self.toolhead.move_axis("X", 592)
        self.toolhead.move_axis("Y", 88)
        
        # draw from first vial
        self.vial_carousel.set_vial(source_vial_1)
        self.pipette_handler.dispense_all(3) 
        self.toolhead.move_axis("Z", vial_draw_height)
        self.pipette_handler.draw_ul(amount_1)
        self.toolhead.move_axis("Z", 200)
        
        # dispense fluid 1 into destination
        self.vial_carousel.set_vial(destination_vial)
        self.toolhead.move_axis("Z", vial_draw_height)
        self.pipette_handler.dispense_all(1)
        self.toolhead.move_axis("Z", 200)
        
        # draw from first vial
        self.vial_carousel.set_vial(source_vial_2)
        self.pipette_handler.dispense_all(3) 
        self.toolhead.move_axis("Z", vial_draw_height)
        self.pipette_handler.draw_ul(amount_2)
        self.toolhead.move_axis("Z", 200)
        
        # dispense fluid 1 into destination
        self.vial_carousel.set_vial(destination_vial)
        self.toolhead.move_axis("Z", vial_draw_height)
        self.pipette_handler.dispense_all(1)
        
        # mix fluids together
        for i in range(5):
            self.pipette_handler.draw_ul(10)
            self.pipette_handler.dispense_all(1)
        
        self.toolhead.move_axis("Z", 200)
        
    def dispense(self, duration_s: int):
        """ Dispense all fluid in pippete, assuming there is any"""
        # calculate feedrate
        self.pipette_handler.dispense_all(duration_s)
        
    def set_grab_angle(self, angle: int):
        self.pipette_handler.set_grabber_angle(angle)
    
    def put_away_pipette(self):
        current_pipette = self.pipette_handler.get_pippete_index()
        
        if not current_pipette:
            self.logger.debug("No pipette held, returning")
            return
        
        self.move_to_location("pipette stand")
        if current_pipette == 0:
            self.toolhead.move_axis("Y", self.pipette_handler.STAND_0_Y)
        else:
            self.toolhead.move_axis("Y", self.pipette_handler.STAND_1_Y)
            
        self.toolhead.move_axis("Z", 40, relative=True) # raise
        self.toolhead.move_axis("X", 120, relative=True) #move forward
        self.toolhead.move_axis("Z", -40, relative=True) #lower into stand
        self.pipette_handler.open_grabber()
        self.toolhead.move_axis("X", -120, relative=True) #move backwards
        
        self.pipette_handler.set_pipette()
        
    
    
    
    def set_0(self):
        self.pipette_handler.set_actuator_position(97)
        self.pipette_handler.set_pipette(0)
        self.toolhead.move_axis("Z", 200)
        self.move_to_location("pipette stand")
        self.pipette_handler.set_grabber_angle(145)
        self.toolhead.move_axis("X", 120, relative=True) #move forward
        self.pipette_handler.set_grabber_angle(48)
        self.toolhead.move_axis("Z", 40, relative=True) # raise
        self.toolhead.move_axis("X", -120, relative=True) #move backwards
        
    def set_1(self):
        self.pipette_handler.set_actuator_position(97)
        self.pipette_handler.set_pipette(1)
        
        self.move_to_location("pipette stand")
        self.toolhead.move_axis("Z", 200)
        self.toolhead.move_axis("Y", 151)
        self.toolhead.move_axis("Z", 128)
        self.pipette_handler.set_grabber_angle(145)
        self.toolhead.move_axis("X", 120, relative=True) #move forward
        self.pipette_handler.set_grabber_angle(48)
        self.toolhead.move_axis("Z", 40, relative=True) # raise
        self.toolhead.move_axis("X", -120, relative=True) #move backwards
        
    def put_0(self):
        self.pipette_handler.set_actuator_position(97)
        self.toolhead.move_axis("Z", 200)
        self.move_to_location("pipette stand")
        self.toolhead.move_axis("Z", 40, relative=True) # raise
        self.toolhead.move_axis("X", 120, relative=True) #move forward
        self.toolhead.move_axis("Z", -40, relative=True) # raise
        self.pipette_handler.set_grabber_angle(145)
        self.toolhead.move_axis("X", -120, relative=True) #move backwards
    
    def put_1(self):
        self.pipette_handler.set_actuator_position(97)
        self.toolhead.move_axis("Z", 200)
        self.move_to_location("pipette stand")
        self.toolhead.move_axis("Z", 200)
   
        self.toolhead.move_axis("Y", 151)
        self.toolhead.move_axis("Z", 168)
        self.toolhead.move_axis("X", 120, relative=True) #move forward
        self.toolhead.move_axis("Z", -40, relative=True) # raise
        self.pipette_handler.set_grabber_angle(145)
        self.toolhead.move_axis("X", -120, relative=True) #move backwards
    
    def set_pipette(self, target_pipette: int):
        # Set Position of the plunger before picking up pipette (number needs to be tested first)
        self.pipette_handler.set_actuator_position(97)

        current_pipette = self.pipette_handler.get_pippete_index()
        self.toolhead.move_axis("Z", 145)
        
        #self.move_to_location("pipette pickup")
        #move in front of first pipette stand
        self.move_to_location("pipette stand")
        # self.toolhead.move_axis("Y", 85)
        # self.toolhead.move_axis("Z", 148)
        # self.toolhead.move_axis("X", 593)
        
        # if we have a pipette and its not the one we want, put it away
        if current_pipette and current_pipette != target_pipette:
            if current_pipette == 0:
                self.toolhead.move_axis("Y", self.pipette_handler.STAND_0_Y)
            else:
                self.toolhead.move_axis("Y", self.pipette_handler.STAND_1_Y)
            
            self.toolhead.move_axis("Z", 40, relative=True) # raise
            self.toolhead.move_axis("X", 120, relative=True) #move forward
            self.toolhead.move_axis("Z", -40, relative=True) #lower into stand
            self.pipette_handler.open_grabber()
            self.toolhead.move_axis("X", -120, relative=True) #move backwards
        
        if current_pipette == 0:
            self.toolhead.move_axis("Y", self.pipette_handler.STAND_0_Y)
        else:
            self.toolhead.move_axis("Y", self.pipette_handler.STAND_1_Y)
            
        self.pipette_handler.open_grabber()
        self.toolhead.move_axis("X", 120, relative=True) #move forward
        self.pipette_handler.close_grabber()
        self.toolhead.move_axis("Z", 40, relative=True) # raise
        self.toolhead.move_axis("X", -120, relative=True) #move backwards
        
        self.pipette_handler.set_pipette(target_pipette)
        
    def eject_tip(self):
        self.pipette_handler.eject_tip()
        
    def set_eject_angle(self, angle: int):
        self.pipette_handler.set_eject_angle(angle)

    # -------- SPECTROMETER MOVES --------

    def measure_spectrum(self, measurement_type: str):
        """
        Captures a spectrum using the spectrometer and stores the data.
        
        Args:
            measurement_type (str): Label for the measurement (e.g., 'Background', 'Reference', 'Sample')
        """
        if not self.spectrometer or not self.spectrometer.is_connected():
            raise Exception("Spectrometer is not connected")

        self.logger.info(f"Starting spectrometer measurement: {measurement_type}")

        # Request wavelengths if not already retrieved
        if not hasattr(self, "wavelengths") or not isinstance(self.wavelengths, np.ndarray) or self.wavelengths.size == 0:
            self.logger.info("Retrieving wavelength data...")
            self.wavelengths = self.spectrometer.read_wavelengths()

        # Capture intensity data
        self.logger.info("Capturing spectrum intensity data...")
        intensities = self.spectrometer.read_spectrum(measurement_type)
        if self.spectrometer_frame:
            self.spectrometer_frame.update_plot()
        # Store the measurement
        if isinstance(intensities, np.ndarray) and intensities.size > 0 and \
           isinstance(self.wavelengths, np.ndarray) and self.wavelengths.size > 0 and \
           intensities.shape == self.wavelengths.shape:

                
            if not hasattr(self, "measurements"):
                self.measurements = {}

            self.measurements[measurement_type] = {
                "wavelengths": self.wavelengths,
                "intensities": intensities
            }

            self.logger.info(f"Measurement '{measurement_type}' captured successfully.")
        else:
            self.logger.warning(f"Incomplete data for measurement '{measurement_type}'. Skipping.")

    def reset_kill(self):
        """Reset any kill state on hardware so operations can resume."""
        self.logger.debug("MoveRegistry: resetting kill state on hardware")
        try:
            if hasattr(self, 'control_board') and self.control_board:
                if hasattr(self.control_board, 'is_killed') and not self.control_board.is_killed():
                    self.logger.debug("MoveRegistry: control board kill state already clear")
                elif hasattr(self.control_board, 'reset_kill'):
                    self.control_board.reset_kill()
        except Exception as e:
            self.logger.exception(f"Error while resetting control board kill state: {e}")
        # Ensure spincoater run waits are unblocked so run() doesn't hang
        try:
            if self.spin_coater and hasattr(self.spin_coater, 'done'):
                # mark done so any waiting thread can continue
                self.spin_coater.done.set()
                # give a short moment and then clear to restore initial state
                sleep(0.1)
                try:
                    self.spin_coater.done.clear()
                except Exception:
                    pass
        except Exception as e:
            self.logger.exception(f"Error while resetting spin coater state: {e}")
        
    def automated_measurement(self):
        """Runs the full spectrometer measurement process."""
        measurement_types = ["Background", "Reference", "Sample"]
        
        for measurement in measurement_types:
            self.measure_spectrum(measurement)
            sleep(1.0) 
            
        save_all_to_csv(self.wavelengths, self.measurements)
        plot_spectra(self.wavelengths, self.measurements)
        
        self.logger.info("All spectrometer measurements completed successfully.")
    
    # -------- VIAL CAROUSEL MOVES --------
    def set_vial(self, vial_num: int):
        self.vial_carousel.set_vial(vial_num)
        
    # -------- INFEED MOVES --------
    def set_infeed_angle(self, angle: int):
        
        current_angle = int(self.infeed.servo.angle)
        step = 1 if angle > current_angle else -1

        for subangle in range(current_angle, angle, step):
            self.infeed.servo.angle = subangle
            sleep(0.1)
        self.infeed.servo.angle = angle
        
    def open_infeed(self):
        self.set_infeed_angle(80)
        
    def close_infeed(self):
        self.set_infeed_angle(0)
    
