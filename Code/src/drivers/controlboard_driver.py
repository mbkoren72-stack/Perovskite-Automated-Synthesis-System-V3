from queue import Queue
import logging
import threading
import time
import re
from time import sleep
import serial
import serial.threaded


# DEFAULT_SPEED = 1000


class ControlBoard():

    def __init__(self):

        self.logger = logging.getLogger("Main Logger")

        self.positions = {"X": 0,
                          "Y": 0,
                          "Z": 0,
                          "A": 0,
                          "B": 0}
        self.serial = None
        self.reader_thread = None

        self.received_ok = threading.Event()
        
        self.relative_positioning_enabled = False
        # Internal event used to signal an emergency stop / kill
        self._kill_event = threading.Event()
        # Lock to serialize writes to the serial port and avoid interleaved bytes
        self._write_lock = threading.RLock()
        # Lock to protect concurrent access to positions
        self._positions_lock = threading.Lock()
        # Optional raw serial logging handle (opened by enable_raw_logging)
        self._raw_log_handle = None
        # Event to indicate a move-level error (e.g. homing failed)
        self._move_error = threading.Event()
        self._last_move_error_line = None
        self._connect_lock = threading.Lock()
        self._command_state_lock = threading.Lock()
        self._sent_command_count = 0
        self._acknowledged_command_count = 0
        self._ack_event = threading.Event()
        self._position_update_count = 0
        self._position_event = threading.Event()

    def connect(self):
        """Connect to the control board and start the reader thread."""
        if not self._connect_lock.acquire(blocking=False):
            self.logger.debug("Control board connection attempt ignored; connection already in progress")
            return False

        port = "/dev/control_board"
        try:
            if self.is_connected():
                self.logger.debug("Control board already connected")
                return True

            # Use a finite timeout so reads don't block forever and freeze the app
            self.serial = serial.Serial(port, 115200, timeout=1.0)
            self._kill_event.clear()
            self._last_move_error_line = None
            self._reset_command_tracking()
            # Start reader thread before sending initialization commands
            self._begin_reader_thread()
            try:
                # Reload stored settings; require reliable send but don't crash the app
                self.send_message("M501", require_lock=True)
            except Exception as e:
                # Log and continue; connection is established even if init command failed
                self.logger.exception(f"Warning: failed to send init command after connect: {e}")
            self.logger.info(f"Connected to control board on port {port}")
            return True
        except Exception as e:
            # Catch all so connecting from UI won't crash the app
            self.logger.error(f"Error connecting to control board: {e}")
            try:
                if getattr(self, 'serial', None):
                    try:
                        self.serial.close()
                    except Exception:
                        pass
                    self.serial = None
            except Exception:
                pass
            return False
        finally:
            self._connect_lock.release()
    
    def disconnect(self):
        if not self.is_connected():
            return
        try:
            self.serial.close()
        finally:
            self.serial = None
            self.reader_thread = None
            self._ack_event.set()
            self._position_event.set()
        # Close raw log handle if open
        try:
            if getattr(self, '_raw_log_handle', None):
                try:
                    self._raw_log_handle.close()
                except Exception:
                    pass
                self._raw_log_handle = None
        except Exception:
            pass
        self.logger.debug("Control Board Disconnected")
            
    def is_connected(self) -> bool:
        return self.serial is not None and self.serial.is_open

    def is_killed(self) -> bool:
        return self._kill_event.is_set()

    def _reset_command_tracking(self):
        with self._command_state_lock:
            self._sent_command_count = 0
            self._acknowledged_command_count = 0
            self._position_update_count = 0
        self._ack_event.clear()
        self._position_event.clear()
        self.received_ok.clear()
        try:
            self._move_error.clear()
        except Exception:
            pass

    def _reserve_command_slot(self) -> int:
        with self._command_state_lock:
            self._sent_command_count += 1
            return self._sent_command_count

    def _record_command_ack(self):
        with self._command_state_lock:
            self._acknowledged_command_count += 1
        self.received_ok.set()
        self._ack_event.set()

    def _get_ack_count(self) -> int:
        with self._command_state_lock:
            return self._acknowledged_command_count

    def _record_position_update(self):
        with self._command_state_lock:
            self._position_update_count += 1
        self._position_event.set()

    def _get_position_update_count(self) -> int:
        with self._command_state_lock:
            return self._position_update_count
    
    def kill(self):
        """Send emergency stop to the control board and unblock waits.
        """
        self.logger.error("Emergency stop requested on control board")
        # Mark kill so other methods can abort early
        try:
            self._kill_event.set()
        except Exception:
            pass

        # Try to send the emergency stop command
        try:
            if self.is_connected():
                self.send_message("M112", require_lock=True)
        except Exception as e:
            self.logger.exception(f"Failed to send emergency stop: {e}")

        # Wake any threads waiting on OK so they can exit quickly
        try:
            self.received_ok.set()
            self._ack_event.set()
            self._position_event.set()
        except Exception:
            pass

    def request_position(self, wait: bool = False, timeout: float = 1.0):
        """Requests the current position of the baord
        """
        if not self.is_connected():
            if wait:
                raise RuntimeError("Control board is not connected")
            return self.positions.copy()

        previous_update_count = self._get_position_update_count() if wait else None
        try:
            self.send_message("M114", require_lock=wait, timeout=timeout)
        except Exception:
            self.logger.exception("Failed to request position from control board")
            if wait:
                raise
            return self.positions.copy()

        if not wait:
            return self.positions.copy()

        deadline = time.monotonic() + max(timeout, 0.1)
        while time.monotonic() < deadline:
            if self._get_position_update_count() > previous_update_count:
                return self.positions.copy()
            if not self.is_connected():
                raise RuntimeError("Control board disconnected while waiting for position response")
            if self.is_killed():
                raise RuntimeError("Control board entered kill state while waiting for position response")
            self._position_event.wait(timeout=min(0.1, deadline - time.monotonic()))
            self._position_event.clear()

        raise TimeoutError("Timed out waiting for position response")

    def enable_raw_logging(self, file_path: str):
        """Enable appending raw incoming serial lines to `file_path` for debugging.
        """
        try:
            # Line-buffered so logs appear promptly
            self._raw_log_handle = open(file_path, "a", buffering=1, encoding="utf-8")
        except Exception as e:
            self.logger.exception(f"Failed to open raw log file {file_path}: {e}")

    def disable_raw_logging(self):
        try:
            if self._raw_log_handle:
                try:
                    self._raw_log_handle.close()
                except Exception:
                    pass
                self._raw_log_handle = None
        except Exception:
            pass

    def _maybe_log_raw_line(self, line: str):
        try:
            if getattr(self, '_raw_log_handle', None):
                try:
                    self._raw_log_handle.write(line + "\n")
                except Exception:
                    pass
        except Exception:
            pass

    def get_position(self, axis: str):
        """Thread-safe getter for axis position."""
        with self._positions_lock:
            return self.positions.get(axis)

    def _update_positions_from_line(self, line: str):
        """Parses the status line containing X:,Y:,Z: etc and updates the  positions."""
        try:
            # Expect lines like: 'X:0.00 Y:0.00 Z:0.00 A:0.00 B:0.00'
            # Use regex to tolerate optional spaces after the colon and different formatting
            # Be permissive and case-insensitive when matching axis prefixes
            updated = False
            for key in list(self.positions.keys()):
                try:
                    m = re.search(rf"{key}:\s*([+-]?\d+(?:\.\d+)?)", line, re.IGNORECASE)
                    if m:
                        val = float(m.group(1))
                        with self._positions_lock:
                            self.positions[key] = val
                        updated = True
                except Exception:
                    # ignore parse errors for individual values
                    pass
            if updated:
                self._record_position_update()
        except Exception:
            self.logger.exception("Failed to parse position line")

    def reset_kill(self):
        """Clears the kill state so operations can resume. Currently Does not function due to Firmware messages not being recieved. This is due to the nature of Kill.
        """
        try:
            if not self.is_killed():
                self.logger.debug("Control board kill state already clear")
                return False

            self._kill_event.clear()
            self._reset_command_tracking()
            self.logger.debug("Control board kill state cleared")

            # If connected, attempt to restart firmware and reload settings
            if self.is_connected():
                try:
                    # Request firmware restart to clear M112 state
                    self.logger.info("Sending firmware reset (M999) to control board")
                    self.send_message("M999", require_lock=True)
                    sleep(0.5)
                    # Reload stored settings
                    self.send_message("M501", require_lock=True)
                    sleep(0.2)
                except Exception as e:
                    self.logger.exception(f"Failed to send firmware reset commands: {e}")
            return True
        except Exception:
            self.logger.exception("Failed to clear control board kill state")
            return False

    def resume_from_user_pause(self):
        """Clears the wait-for-user state."""
        if not self.is_connected():
            raise RuntimeError("Control board is not connected")

        self.logger.warning("Sending M108 for clearing firmware wait-for-user state")
        try:
            self._move_error.clear()
        except Exception:
            pass
        self._last_move_error_line = None
        self.send_message("M108", require_lock=True)
        sleep(0.2)
        try:
            self.request_position()
        except Exception:
            pass
        
    def _begin_reader_thread(self):
        self.reader_thread = serial.threaded.ReaderThread(
            serial_instance=self.serial,
            protocol_factory=lambda: ControlBoardLineReader(
                self.logger, self)
        )
        self.reader_thread.daemon = True
        self.reader_thread.start()

    def send_message(self, message: str, require_lock: bool = False, timeout: float = 0.5):
        """Sends a message to the control board.
        """
        if not self.is_connected():
            self.logger.error("Serial is not connected")
            return

        if self.reader_thread is None:
            self.logger.error("Reader thread is not running")
            return

        # preserve the original short command for selective logging
        original_cmd = message.strip()
        if '\r\n' not in message:
            message += "\r\n"

        # Serialize writes to avoid interleaving bytes from concurrent threads
        acquired = False
        command_id = None
        try:
            if require_lock:
                # For required messages try to acquire the lock with a longer timeout
                try:

                    acquired = self._write_lock.acquire(timeout=5.0)
                except Exception:
                    acquired = False
                if not acquired:
                    self.logger.error(f"Timed out waiting for serial write lock for required send: {original_cmd}")
                    raise RuntimeError("Failed to acquire serial write lock for required message")
            else:

                try:
                    acquired = self._write_lock.acquire(timeout=timeout)
                except Exception:
                    acquired = False

                if not acquired:
                    # If we can't acquire the lock quickly, log and skip to avoid blocking UI
                    self.logger.warning(f"Timed out waiting for serial write lock; skipping send: {original_cmd}")
                    return

            try:
                # write via the reader thread's write helper
                self.reader_thread.write(message.encode("utf-8"))
                command_id = self._reserve_command_slot()
                # Don't log M114 requests to avoid spamming the console with position-requests
                if not original_cmd.upper().startswith("M114"):
                    self.logger.debug(f"Sending message: {message}")
            except Exception as e:
                self.logger.exception(f"Failed to send message '{message}': {e}")

        finally:
            if acquired:
                try:
                    self._write_lock.release()
                except Exception:
                    pass
        return command_id
        
        
    def move_axis(self, axis: str, distance_mm: float,
                  feedrate_mm_per_minute: int = 2000,
                  relative: bool = False,
                  finish_move: bool = True):
    
        """Takes in an axis, distance and speed to move the gantry"""
    
        if axis not in self.positions.keys():
            raise ValueError(f"Invalid axis {axis}")
    
        if relative and distance_mm == 0:
            return
    
        # Abort early if an emergency kill has been requested
        if getattr(self, '_kill_event', None) is not None and self._kill_event.is_set():
            self.logger.warning("Move aborted: control board in kill state")
            raise RuntimeError("ControlBoard is in kill state")
    
        # Don't go crazy with these axes
        if (axis == "Z" or axis == "A" or axis == "B") and feedrate_mm_per_minute == 2000:
            feedrate_mm_per_minute = 600
    
        # Keep the ENTIRE movement sequence under one lock.
        # RLock allows send_message() to acquire this same lock again.
        with self._write_lock:
    
            # Set positioning mode
            if relative:
                self.send_message("G91", require_lock=True)
            else:
                self.send_message("G90", require_lock=True)
    
            sleep(0.1)
    
            # Perform movement
            self.send_message(
                f"G0 {axis}{distance_mm} F{feedrate_mm_per_minute}",
                require_lock=True
            )
    
            sleep(0.1)
    
            # Wait for movement to complete
            if finish_move:
                self.finish_moves()
                sleep(0.1)
    
            # Return to absolute positioning
            if relative:
                self.send_message("G90", require_lock=True)
                sleep(0.1)

    def finish_moves(self):


        """Waits for the move to finish"""
        if not self.is_connected():
            self.logger.error("Serial is not connected")
            if require_lock:
                raise RuntimeError("Control board is not connected")
            return None
        
        if self.reader_thread is None:
            self.logger.error("Reader thread is not running")
            if require_lock:
                raise RuntimeError("Control board reader thread is not running")
            return None
        # Clear any previous move error marker
        try:
            self._move_error.clear()
        except Exception:
            pass
        self._last_move_error_line = None
        sleep(0.1)
        try:
            command_id = self.send_message("M400", require_lock=True)
        except Exception:
            # send_message already logs failures
            command_id = None

        if command_id is None:
            raise RuntimeError("Failed to send M400 to control board")

        self.logger.debug("Waiting for move to finish (interruptible)")

        timeout = 120.0

        completed = False
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if not self.is_connected():
                raise RuntimeError("Control board disconnected while waiting for move completion")
            # If a kill has been requested, break out early
            if self.is_killed():
                self.logger.info("Finish moves interrupted by kill")
                break

            # If firmware reported a move-level error (e.g. homing failed), abort
            if getattr(self, '_move_error', None) is not None and self._move_error.is_set():
                self.logger.error("Move aborted: firmware reported error")
                break

            if self._get_ack_count() >= command_id:
                completed = True
                break

            wait_time = min(0.1, deadline - time.monotonic())
            self._ack_event.wait(timeout=wait_time)
            self._ack_event.clear()

        if self.is_killed():
            raise RuntimeError("Move aborted by emergency stop")
        # If we exited because of a firmware-reported move error, raise so
        # callers (e.g. procedure runner) can abort and handle it.
        if getattr(self, '_move_error', None) is not None and self._move_error.is_set():
            error_line = (self._last_move_error_line or "").strip()
            if error_line:
                raise RuntimeError(f"Firmware reported a move error: {error_line}")
            raise RuntimeError("Firmware reported a move error (see logs)")
        if not completed:
            self.logger.error(f"Timed out waiting for move completion after {timeout:.1f}s")
            raise TimeoutError(f"Timed out waiting for move completion after {timeout:.1f}s")
        try:
            self.request_position(wait=True, timeout=2.0)
        except Exception as exc:
            self.logger.warning(f"Failed to refresh gantry position after move completion: {exc}")
        




class ControlBoardLineReader(serial.threaded.LineReader):
    """This reads lines from the control board on a separate thread."""

    TERMINATOR = b"\n"
    POSITION_PREFIXS = ["X:", "Y:", "Z:", "A:", "B:"]
    
    def __init__(self, logger: logging.Logger, control_board: ControlBoard):
        """Initialize with optional logger."""
        super().__init__()
        self.logger = logger
        self.control_board = control_board
        self.logger.debug("Line Reader Started")

    @staticmethod
    def _is_move_error_line(line: str) -> bool:
        normalized = line.strip().lower()
        if normalized.startswith("error"):
            return True

        informational_markers = (
            "endstop hit",
            "endstops hit",
        )
        if any(marker in normalized for marker in informational_markers):
            return False

        error_markers = (
            "homing failed",
            "home xyz first",
            "must home",
            "printer halted",
            "kill() called",
            "probe failed",
            "unknown message",
        )
        return any(marker in normalized for marker in error_markers)

    @staticmethod
    def _is_paused_for_user_line(line: str) -> bool:
        return "busy: paused for user" in line.strip().lower()

    def _record_move_error(self, line: str):
        try:
            self.control_board._last_move_error_line = line.strip()
            self.control_board._move_error.set()
        except Exception:
            pass

    def handle_line(self, line):
        """Process each received line."""
        line = line.strip()

        # Write raw line to debug file if enabled
        try:
            # keep raw logging lightweight and non-blocking
            self.control_board._maybe_log_raw_line(line)
        except Exception:
            pass

        if not line:
            return

        # Ignored echoed M114 commands (some firmware echo commands back)
        if line.upper().startswith("M114"):
            return

        if any(prefix in line for prefix in self.POSITION_PREFIXS):
            try:
                self.control_board._update_positions_from_line(line)
            except Exception:
                self.logger.exception("Failed to update positions from line")
            # If firmware also returned an 'ok' token in the same line, set it.
            if line.lower().startswith("ok"):
                self.control_board._record_command_ack()
            # Detect common firmware status echoes indicating a failed move/homing
            # and record a move-level error so waiting loops can abort.
            try:
                if self._is_move_error_line(line):
                    self._record_move_error(line)
            except Exception:
                pass
            return

        if line.lower().startswith("ok"):
            self.control_board._record_command_ack()
            return

        if self._is_paused_for_user_line(line):
            self.logger.error(f"Firmware paused for user: {line}")
            self._record_move_error(line)
            return

        if line.strip().lower().startswith("echo:busy: processing"):
            self.logger.debug(f"Firmware: {line}")
            return
        if self._is_move_error_line(line) or line.lower().startswith("echo"):
            self.logger.warning(f"Firmware: {line}")
            try:
                if self._is_move_error_line(line):
                    self._record_move_error(line)
            except Exception:
                pass
        else:
            self.logger.debug(f"Received: {line}")
            
    def connection_lost(self, exc):
        """Handles the loss of connection for the Serial."""
        if exc:
            self.logger.error(f"Serial connection lost: {exc}")
        else:
            self.logger.info("Serial connection closed")
        self.control_board.disconnect()


