import threading
import queue
import logging
import time
from datetime import datetime, timedelta
from services.move_registry import MoveRegistry
# pylint: disable=line-too-long


class ProcedureHandler(threading.Thread):
    """This class controls the main procedure thread, which calls functions .
    """

    def __init__(self, move_registry):
        super().__init__(name="ProcedureHandler",daemon=True)
        
        self.logger = logging.getLogger("Main Logger")
        self.move_registry = move_registry

        self.procedure = None
        self.current_step = 0
        
        self.paused = threading.Event()
        self.started = threading.Event()
        # Set while the worker thread is NOT inside a procedure run
        self.idle = threading.Event()
        self.idle.set()
        # Set by kill() so the run loop treats the failing step as an abort
        self._killed = threading.Event()

        self.error_flag = False
        self.error_step_index = None
         
        self.procedure_timer = Timer()
        self.start()
        
        # Configurable minimum step duration (in seconds) to ensure UI updates
        self.min_step_duration = 0.5    

    def set_procedure(self, procedure: list):
        """Set the procedure to be run.
        Args:
            procedure (list): list of moves to run.
        """
        if self.started.is_set():
            self.logger.error("Cannot change moves until procedure stops")
            return
        
        if not self.move_registry.validate_moves(procedure):
            self.logger.error("Invalid moves in procedure")
            return
         
        self.procedure = procedure

    def run(self):
        """Run the procedure
        """
        while True:
            # wait until user has started procedure
            self.started.wait()
            self.idle.clear()
            
            self.current_step = 0
            self.error_flag = False
            self.error_step_index = None
            
            while self.started.is_set() and (self.current_step < len(self.procedure)):
                
                if self.started.is_set() == False:
                    self.logger.info("Stopping")
                    break
                
                move = self.procedure[self.current_step]
                
                func_name = move[0]
                func_args = move[1:]
                
                # Format args for logging
                args_str = ", ".join(str(arg) for arg in func_args) if func_args else ""
                
                # Log the step we're executing
                self.logger.info(f"Step {self.current_step + 1}/{len(self.procedure)}: {func_name}({args_str})")
                
                step_start_time = time.time()

                # try running the move, stopping if there are any errors
                try:
                    self.move_registry.move_dict[func_name](*func_args)
                    self.logger.debug(f"Step {self.current_step} completed successfully")
                except Exception as e:
                    if self._killed.is_set():
                        self.logger.warning(f"Step {self.current_step} aborted by kill")
                    else:
                        self.logger.error(f"Error in step {self.current_step}: {e}")
                    self.error_flag = True
                    self.error_step_index = self.current_step
                    break
                
                # Ensure minimum step duration for UI responsiveness
                elapsed = time.time() - step_start_time
                if elapsed < self.min_step_duration:
                    sleep_time = self.min_step_duration - elapsed
                    time.sleep(sleep_time)
                
                self.current_step += 1
                time.sleep(0.2)
            
                # if procedure is paused after finishing previous move
                if self.paused.is_set():
                    self.logger.info("Paused at step {}".format(self.current_step))
                    self.procedure_timer.pause()
                    while self.paused.is_set():
                        time.sleep(0.1)
                    self.procedure_timer.unpause()
                    self.logger.info("Resumed from step {}".format(self.current_step))
            
            if self.current_step >= len(self.procedure):
                self.logger.info("Procedure completed successfully - all {} steps executed".format(len(self.procedure)))
            
            self.stop()
            self.logger.debug("Procedure Ended")
            self.idle.set()

    def begin(self):
        """Begin the procedure
        """
        if not self.procedure:
            self.logger.error("No procedure set")
            return
         if not self.idle.is_set():
            self.logger.error("Previous run is still stopping; try again in a moment")
            return
        # Clear any previous emergency kill state before starting
        try:
            if hasattr(self.move_registry, 'reset_kill'):
                if self.move_registry.reset_kill() is False:
                    self.logger.error("Hardware is not ready after kill; not starting")
                    return
        except Exception:
            self.logger.exception("Failed to reset kill state on begin")
            return
        self._killed.clear()
   
        self.started.set()
        self.paused.clear()
        self.procedure_timer.start()
        self.logger.info("Starting Procedure...")

    def stop(self):
        """Stop the procedure.
        """
        self.started.clear()
        self.paused.clear()
        self.procedure_timer.pause()
        self.logger.info("Stopping procedure...")
        
            
    def kill(self, rearm: bool = True, timeout: float = 10.0) -> bool:
        """Emergency stop: halt all hardware, end the run, then re-arm.
 
        Blocks until the worker thread has left the current step (or
        `timeout` expires), so call it from a background thread, not the UI.
        Returns True if the system is ready to run again.
        """
        self._killed.set()
        try:
            self.move_registry.kill()
        except Exception:
            self.logger.exception("Error while executing move_registry.kill()")
        # Ensure the procedure is no longer considered started so it can be restarted
        self.stop()
        self.logger.error("Emergency stop triggered; procedure stopped")
 
        if not self.idle.wait(timeout):
            self.logger.error(
                f"Procedure step did not stop within {timeout:.0f}s after kill; "
                "the system stays killed"
            )
            return False
 
        if not rearm:
            return True
 
        try:
            ready = self.move_registry.reset_kill() is not False
        except Exception:
            self.logger.exception("Failed to re-arm hardware after kill")
            ready = False
        if ready:
            self._killed.clear()
            self.logger.info("Kill complete; system ready (re-home before running moves)")
        return ready
 
    def is_busy(self) -> bool:
        """True while a procedure run is in progress or still unwinding."""
        return not self.idle.is_set()

    def pause(self):
        """Pause the procedure."""
        self.paused.set()
        self.logger.info("Pausing procedure...")

    def resume(self) -> None:
        """Resume the procedure."""
        self.paused.clear()
        self.logger.info("Resuming procedure...")
        
    def get_time_elapsed(self) -> timedelta:
        return self.procedure_timer.get_time()
        
    def get_progress(self) -> float:
        if self.procedure is None:
            return 0
      
        return self.current_step / len(self.procedure)
    
    def get_current_step_index(self):
        """Get the current step index in the procedure"""
        return self.current_step

    def has_error(self):
        """Check if an error occurred during execution"""
        return self.error_flag

    def get_error_step_index(self):
        """Get the index of the step that caused an error"""
        return self.error_step_index
    
    def set_min_step_duration(self, duration_seconds: float):
        """Set the minimum duration each step should take (for visual feedback)
        
        Args:
            duration_seconds (float): Minimum duration in seconds (e.g., 0.5 for 500ms)
        """
        self.min_step_duration = max(0, duration_seconds)
        self.logger.debug(f"Minimum step duration set to {self.min_step_duration}s")
    
    #set the number of procedurs to run
    def set_procedure_loop_count(self, new_loop_count):
        if self.started.is_set():
            self.logger.error("Cannot change loop count until procedure stops")
            return
        
        
        self.loop_count = new_loop_count
        
class Timer():
    def __init__(self):
        self.start_time = None
        self.pause_time = 0
        self.is_paused = False
        
    def start(self):
        self.start_time = datetime.now()
        self.is_paused = False
        
    def pause(self):
        if self.is_paused:
            return
            
        self.pause_time = datetime.now()
        self.is_paused = True
    
    def unpause(self):
        if not self.is_paused:
            return
        
        last_pause_time = datetime.now() - self.pause_time
        self.start_time = self.start_time + last_pause_time
        self.is_paused = False
        
    def get_time(self):
        if self.start_time is None:
            return timedelta(0)
        
        if self.is_paused:
            return self.pause_time.replace(microsecond=0) - self.start_time.replace(microsecond=0)
        else:
            return datetime.now().replace(microsecond=0) - self.start_time.replace(microsecond=0)
