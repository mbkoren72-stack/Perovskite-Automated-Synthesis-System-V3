from logging import Logger
import logging
import customtkinter as ctk
from tkinter import filedialog
import sys
import os

from ...components.constants import *

# import procedure file driver
path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
sys.path.append(path)
from drivers.procedure_file_driver import ProcedureFile


class StepStateFrame(ctk.CTkFrame):
    """Visual representation of a single procedure step"""

    def __init__(self, master, text):
        super().__init__(master, corner_radius=0, height=60)

        self.label = ctk.CTkLabel(self, text=text, anchor="w")
        self.label.pack(fill="both", expand=True, padx=10)

        # Placeholder for future GIF
        self.spinner = None

        self.set_state("idle")

    def set_state(self, state):
        if state == "idle":
            self.configure(fg_color=FOREGROUND_COLOR)  # gray

        elif state == "running":
            self.configure(fg_color="#309df0")  # blue

        elif state == "complete":
            self.configure(fg_color="#3ee646")  # green

        elif state == "error":
            self.configure(fg_color="#e82c45")  # red


class ProcedureQueueFrame(ctk.CTkFrame):
    """Displays live procedure execution with step states"""

    def __init__(self, master, procedure_handler, **kwargs):
        super().__init__(master, fg_color=FOREGROUND_COLOR, corner_radius=0, width=300)

        self.procedure_handler = procedure_handler
        self.logger = logging.getLogger("Main Logger")
        self.killed = False
        self._kill_thread = None

        self.steps = []
        self.step_frames = []

        # --- TITLE ---
        self.title_label = ctk.CTkLabel(
            self,
            text="Procedure Overview",
            font=("Arial", 20, "bold"),
            anchor="w"
        )
        self.title_label.grid(row=0, column=0, columnspan=4, padx=20, pady=20, sticky="ew")

        # --- CONTROLS ---
        self.start_button = ctk.CTkButton(self, text="Start", command=self._start_procedure)
        self.start_button.grid(row=1, column=0, padx=5, pady=10)

        self.pause_button = ctk.CTkButton(self, text="Pause", command=self._toggle_pause)
        self.pause_button.grid(row=1, column=1, padx=5, pady=10)

        self.stop_button = ctk.CTkButton(self, text="Stop", command=self._stop_procedure)
        self.stop_button.grid(row=1, column=2, padx=5, pady=10)

        self.kill_button = ctk.CTkButton(
            self,
            text="Kill",
            fg_color="#a10e22",
            hover_color="#45060f",
            command=self._kill_procedure
        )
        self.kill_button.grid(row=1, column=3, padx=5, pady=10)

        # --- PROGRESS ---
        self.time_label = ctk.CTkLabel(self, text="")
        self.time_label.grid(row=2, column=0)

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.grid(row=2, column=1, columnspan=2, sticky="ew")

        self.progress_label = ctk.CTkLabel(self, text="0%")
        self.progress_label.grid(row=2, column=3)

        # --- IMPORT ---
        self.import_button = ctk.CTkButton(self, text="Import", command=self._import_procedure)
        self.import_button.grid(row=3, column=0)

        self.current_procedure_label = ctk.CTkLabel(self, text="No Procedure Loaded")
        self.current_procedure_label.grid(row=3, column=1, columnspan=3)

        # --- STEP DISPLAY ---
        self.steps_container = ctk.CTkScrollableFrame(self, fg_color="#1f1f1f")
        self.steps_container.grid(row=4, column=0, columnspan=4, sticky="nsew", padx=10, pady=10)

        self.grid_rowconfigure(4, weight=1)

        self.load_default_procedure()
        self._update()

    # -------------------------
    # STEP BUILDING
    # -------------------------

    def _format_step_name(self, step):
        """Convert move format into readable string"""
        if isinstance(step, (list, tuple)) and len(step) > 0:
            func_name = step[0]
            args = ", ".join(map(str, step[1:]))
            return f"{func_name}({args})" if args else func_name
        return str(step)

    def _build_steps(self, procedure):
        """Rebuild step UI"""
        for frame in self.step_frames:
            frame.destroy()

        self.step_frames.clear()
        self.steps = procedure

        for step in procedure:
            name = self._format_step_name(step)
            frame = StepStateFrame(self.steps_container, name)
            frame.pack(fill="x", padx=5, pady=3)
            self.step_frames.append(frame)

    # -------------------------
    # STATE UPDATE
    # -------------------------

    def _update_step_states(self):
        if not self.steps:
            return

        current = self.procedure_handler.get_current_step_index()
        error = self.procedure_handler.has_error()
        error_index = self.procedure_handler.get_error_step_index()

        for i, frame in enumerate(self.step_frames):
            if error and i == error_index:
                frame.set_state("error")
            elif i < current:
                frame.set_state("complete")
            elif i == current and self.procedure_handler.started.is_set():
                frame.set_state("running")
            else:
                frame.set_state("idle")

    # -------------------------
    # MAIN LOOP
    # -------------------------

    def _update(self):
        if not self.procedure_handler.started.is_set():
            self.start_button.configure(state="normal")
            self.pause_button.configure(state="disabled", text="Pause")
            self.stop_button.configure(state="disabled")
            self.import_button.configure(state="normal")
        else:
            self.start_button.configure(state="disabled")
            self.pause_button.configure(state="normal")
            self.stop_button.configure(state="normal")
            self.import_button.configure(state="disabled")
            
        if self.killed:
            if self._kill_thread is not None and not self._kill_thread.is_alive():
                # Kill finished (hardware stopped and re-armed, or failed):
                # give the controls back so the user can restart.
                self.killed = False
                self._kill_thread = None
                self.kill_button.configure(state="normal", text="Kill")
            else:
                self.start_button.configure(state="disabled")
                self.pause_button.configure(state="disabled")
                self.stop_button.configure(state="disabled")
                self.kill_button.configure(state="disabled", text="Killing...")

        # Progress
        progress = self.procedure_handler.get_progress()
        self.progress_bar.set(progress)
        self.progress_label.configure(text=f"{int(progress * 100)}%")
        self.time_label.configure(text=self.procedure_handler.get_time_elapsed())

        self._update_step_states()

        self.after(200, self._update)

    # -------------------------
    # CONTROLS
    # -------------------------

    def _start_procedure(self):
        self.procedure_handler.begin()

    def _toggle_pause(self):
        if not self.procedure_handler.paused.is_set():
            self.procedure_handler.pause()
            self.pause_button.configure(text="Resume")
        else:
            self.procedure_handler.resume()
            self.pause_button.configure(text="Pause")

    def _stop_procedure(self):
        self.procedure_handler.stop()

    def _kill_procedure(self):
        if self.killed:
            return
        self.killed = True
        self.pause_button.configure(text="Pause")
        # Run kill in background: it waits for the current step to unwind and
        # for the control board to confirm it is responsive again.
        import threading as _threading
        self._kill_thread = _threading.Thread(
            target=self.procedure_handler.kill, name="KillProcedure", daemon=True
        )
        self._kill_thread.start()

    # -------------------------
    # IMPORT
    # -------------------------

    def _import_procedure(self):
        file_path = filedialog.askopenfilename(
            initialdir="src/procedures/",
            filetypes=(("Yaml files", "*.yml*"),)
        )

        if file_path:
            file = ProcedureFile().Open(path=file_path)
            procedure = file["Procedure"]

            self.procedure_handler.set_procedure(procedure)

            self.current_procedure_label.configure(
                text=f"Current Procedure: {os.path.basename(file_path)}"
            )

            self._build_steps(procedure)

    def load_default_procedure(self):
        """Load the default procedure from disk at startup."""
        # Try multiple paths to find the default procedure
        possible_paths = [
            os.path.join("procedures", "default_procedure.yml"),
            os.path.join("src", "procedures", "default_procedure.yml"),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "procedures", "default_procedure.yml"))
        ]
        
        for path in possible_paths:
            try:
                file = ProcedureFile().Open(path=path)
                if file is None:
                    continue
                    
                procedure = file.get("Procedure")
                if procedure is None:
                    continue

                self.procedure_handler.set_procedure(procedure)
                self.current_procedure = os.path.basename(path)
                self.current_procedure_label.configure(
                    text=f"Current Procedure: {self.current_procedure}"
                )

                self._build_steps(procedure)
                self.logger.info(f"Loaded default procedure: {path}")
                return
                
            except Exception as e:
                continue
        
        # If we get here, no procedure was loaded
        self.logger.warning("Could not load default procedure from any path")
        self.current_procedure_label.configure(
            text="No Procedure Loaded - Use Import to load one"
        )
