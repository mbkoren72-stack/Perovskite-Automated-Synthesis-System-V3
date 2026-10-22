import customtkinter as ctk
from ..components.constants import *

from .file_manager_frame import FileManagerFrame
from .settings_frame import SettingsFrame
from .calibration import ArucoCalibrationFrame

from .procedure_viewer import ProcedureViewerFrame
from .procedure_builder import ProcedureBuilderFrame

from .full_cycle_frame import FullCycleFrame

class TabViewFrame(ctk.CTkFrame):
    """Shell for managing ___, ___, and ____ tabs"""
    def __init__(self, master, dispatcher, move_registry, procedure_handler, **kwargs):
        super().__init__(
            master,
            width = 930,
            height = 700,
            corner_radius = 0,
            fg_color = FOREGROUND_COLOR
        )

        self.dispatcher = dispatcher
        self.move_registry = move_registry
        self.procedure_handler = procedure_handler

        self.columnconfigure(0, weight = 1)
        self.rowconfigure(0, weight = 1)

        self.procedure_builder_frame = ProcedureBuilderFrame(
            master = self, 
            dispatcher = self.dispatcher,
            move_registry = self.move_registry, 
            procedure_handler = self.procedure_handler,
            queue_frame = None
        )
        self.procedure_builder_frame.grid(row = 0, column = 0, padx = 0, pady = 0, sticky = "nsew")
        self.procedure_builder_frame.grid_remove()

        self.procedure_viewer_frame = ProcedureViewerFrame(
            master = self,
            dispatcher = self.dispatcher,
            procedure_handler = self.procedure_handler
            )
        
        self.procedure_viewer_frame.grid(row = 0, column = 0, padx = 0, pady = 0, sticky = "nsew")
        self.procedure_viewer_frame.grid_remove()
        # Pause updates since this tab is not active initially
        self.procedure_viewer_frame.pause_updates()

        self.settings_frame = SettingsFrame(
            master = self,
            procedure_handler = self.procedure_handler
        )
        self.settings_frame.grid(row = 0, column = 0, padx = 0, pady = 0, sticky = "nsew")
        self.settings_frame.grid_remove()

        self.file_manager_frame = FileManagerFrame(master = self)
        self.file_manager_frame.grid(row = 0, column = 0, padx = 0, pady = 0, sticky = "nsew")
        self.file_manager_frame.grid_remove()

        self.aruco_calibration_frame = ArucoCalibrationFrame(
            master = self,
            dispatcher = self.dispatcher
        )
        self.aruco_calibration_frame.grid(row = 0, column = 0, padx = 0, pady = 0, sticky = "nsew")
        self.aruco_calibration_frame.grid_remove()
        
        # Initialize the Full Cycle GUI for automated synthesis
        self.full_cycle_frame = FullCycleFrame(master=self)
        # Position the frame in the same area as the other tabs
        self.full_cycle_frame.grid(
            row=0,
            column=0,
            padx=0,
            pady=0,
            sticky="nsew"
        )
        # Keep the frame hidden until the Full Cycle tab is selected
        self.full_cycle_frame.grid_remove()
        self.procedure_builder_frame.queue_frame = self.procedure_viewer_frame.procedure_queue_frame

        # Dictionary so the goto_tab correctly maps a tab with its frame. 
        # Note: In future development, these names should be linked with their constants in components/constants.py for clarity
        self.frames = {
            "procedure_builder": self.procedure_builder_frame,
            "procedure_viewer": self.procedure_viewer_frame,
            "file_manager": self.file_manager_frame,
            "settings": self.settings_frame,
            "aruco_calibration": self.aruco_calibration_frame,
            "full_cycle": self.full_cycle_frame
        }

        self.current_tab_name = "file_manager" 
        self.frames[self.current_tab_name].grid()

    def goto_tab(self, tab):
        if self.current_tab_name == tab:
            return
        if not(tab in TABS):
            raise TypeError("tab does not exist")

        old_frame = self.frames[self.current_tab_name]
        new_frame = self.frames[tab]

        # Pause updates in the old frame if it has the method
        if hasattr(old_frame, 'pause_updates'):
            old_frame.pause_updates()
        
        old_frame.grid_remove()
        new_frame.grid()
        
        # Resume updates in the new frame if it has the method
        if hasattr(new_frame, 'resume_updates'):
            new_frame.resume_updates()

        self.current_tab_name = tab
        
        print("Tab Set To "+ self.current_tab_name )
