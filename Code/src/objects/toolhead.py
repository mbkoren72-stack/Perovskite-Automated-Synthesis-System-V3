import os
import sys
pp=os.path.abspath(os.path.join(os.path.dirname(__file__), '../'))
sys.path.append(pp)

from drivers.controlboard_driver import ControlBoard
#lara
class Toolhead():
    def __init__(self, control_board: ControlBoard):
        self.control_board = control_board

    def _ensure_connected(self):
        if not self.control_board.is_connected():
            raise RuntimeError("Control board is not connected")

    def home_axes(self, *axes: str):
        logger = self.control_board.logger
        self._ensure_connected()

        for axis in axes:
            try:
                self.control_board.send_message(f"G28 {axis}", require_lock=True)
                self.control_board.finish_moves()
                logger.info(f"Homed {axis}; position {axis}={self.get_position(axis)}")
            except Exception as exc:
                logger.exception(f"Homing {axis} failed")
                raise RuntimeError(f"Failed to home {axis} axis") from exc

    def home_xy(self):
        self.home_axes("Y", "X")
        
    def move_axis(self, axis: str, distance_mm: float, feedrate_mm_per_minute: int = 1000, relative: bool = False, finish_move: bool = True):
        """Move a single axis through the control board.

        Accepts an optional `feedrate_mm_per_minute` (defaults to 1000) and
        passes through to the lower-level `ControlBoard.move_axis`.
        """
        self.control_board.move_axis(axis, distance_mm, feedrate_mm_per_minute, relative=relative, finish_move=finish_move)
        
    def get_position(self, axis):
        # Use control board's thread-safe getter
        try:
            return self.control_board.get_position(axis)
        except Exception:
            return None
    
    def home(self):
        # Home each axis separately and stop immediately on the first failure.
        # This board is more reliable with per-axis G28 commands than a
        # combined homing command.
        self.home_axes("Z", "Y", "X")

    def move_to(self, x: float = None, y: float = None, z: float = None, relative: bool = False, feedrate: int = 1000, coordinated: bool = True):
        """Move multiple axes.

        By default this attempts a coordinated multi-axis `G0` (if
        `coordinated=True`). If the firmware does not reach the requested
        coordinates the method falls back to per-axis moves (Z->X->Y) to
        ensure reliability.
        """
        logger = self.control_board.logger
        logger.info(f"move_to called: x={x}, y={y}, z={z}, relative={relative}, feedrate={feedrate}, coordinated={coordinated}")

        # Check if we have any coordinates to move
        has_move = x is not None or y is not None or z is not None
        if not has_move:
            logger.debug("move_to: no coordinates specified")
            return

        def _position_close(a, b, tol=0.5):
            try:
                return abs(float(a) - float(b)) <= tol
            except Exception:
                return False

        start_positions = {
            "X": self.get_position("X"),
            "Y": self.get_position("Y"),
            "Z": self.get_position("Z"),
        }

        def _expected_position(axis: str, target):
            if target is None:
                return None
            if not relative:
                return target
            start_value = start_positions.get(axis)
            if start_value is None:
                return None
            try:
                return float(start_value) + float(target)
            except Exception:
                return None

        # First attempt coordinated move if requested
        if coordinated:
            try:
                # Ensure mode and send combined move
                if relative:
                    self.control_board.send_message("G91", require_lock=True)
                else:
                    self.control_board.send_message("G90", require_lock=True)

                parts = []
                if x is not None:
                    parts.append(f"X{x}")
                if y is not None:
                    parts.append(f"Y{y}")
                if z is not None:
                    parts.append(f"Z{z}")

                cmd = "G0 " + " ".join(parts) + f" F{feedrate}"
                self.control_board.send_message(cmd, require_lock=True)
                self.control_board.finish_moves()

                # Verify positions; if any axis didn't reach target, fall back
                need_fallback = False
                expected_z = _expected_position("Z", z)
                expected_x = _expected_position("X", x)
                expected_y = _expected_position("Y", y)

                if expected_z is not None and not _position_close(self.get_position("Z"), expected_z):
                    logger.warning(f"Coordinated move: Z did not reach {expected_z}, actual={self.get_position('Z')} -> falling back")
                    need_fallback = True
                if expected_x is not None and not _position_close(self.get_position("X"), expected_x):
                    logger.warning(f"Coordinated move: X did not reach {expected_x}, actual={self.get_position('X')} -> falling back")
                    need_fallback = True
                if expected_y is not None and not _position_close(self.get_position("Y"), expected_y):
                    logger.warning(f"Coordinated move: Y did not reach {expected_y}, actual={self.get_position('Y')} -> falling back")
                    need_fallback = True

                if need_fallback:
                    logger.info("Falling back to per-axis moves")
                    raise RuntimeError("Coordinated move incomplete; fallback requested")

                # Coordinated move succeeded
                logger.info(f"Coordinated move complete; final positions: X={self.get_position('X')}, Y={self.get_position('Y')}, Z={self.get_position('Z')}")
                # Revert to absolute if needed
                if relative:
                    self.control_board.send_message("G90", require_lock=True)
                return
            except Exception as e:
                logger.debug(f"Coordinated move failed or incomplete: {e}")

        # Fallback or non-coordinated: move axes individually (Z->X->Y)
        if z is not None:
            logger.info(f"Moving Z to {z} (absolute={not relative})")
            self.move_axis("Z", z, feedrate_mm_per_minute=feedrate, relative=relative, finish_move=True)
            logger.info(f"Z move complete; reported position: {self.get_position('Z')}")

        if x is not None:
            logger.info(f"Moving X to {x} (absolute={not relative})")
            self.move_axis("X", x, feedrate_mm_per_minute=feedrate, relative=relative, finish_move=True)
            logger.info(f"X move complete; reported position: {self.get_position('X')}")

        if y is not None:
            logger.info(f"Moving Y to {y} (absolute={not relative})")
            self.move_axis("Y", y, feedrate_mm_per_minute=feedrate, relative=relative, finish_move=True)
            logger.info(f"Y move complete; reported position: {self.get_position('Y')}")

        logger.info(f"move_to complete; final position: X={self.get_position('X')}, Y={self.get_position('Y')}, Z={self.get_position('Z')}")

