# Imports
import customtkinter as ctk
from ...components.constants import *
from .camera_frame import CameraFrame
from .spectrometer_frame import SpectrometerFrame
from .procedure_queue_frame import ProcedureQueueFrame

class ProcedureViewerFrame(ctk.CTkFrame):
    """Frame to display current state of procedure"""
    def __init__(self, master, dispatcher, procedure_handler, **kwargs):
        super().__init__(master, fg_color = BACKGROUND_COLOR)

        self.dispatcher = dispatcher
        self.procedure_handler = procedure_handler
        
        self.columnconfigure(0, weight = 1, minsize = 500)
        self.columnconfigure(1, weight = 0)

        self.rowconfigure(0, weight = 0) # Mode Selection
        self.rowconfigure(1, weight = 0) # Procedure queue / camera
        self.rowconfigure(2, weight = 1) # Procedure queue / spectrometer



        # Mode selection buttons
        self.current_mode = "automated"

        self.mode_frame = ctk.CTkFrame(
            master=self,
            fg_color=FOREGROUND_COLOR
        )
        self.mode_frame.grid(
            row=0, column=0, columnspan=2,
            padx=10, pady=10, sticky="ew"
        )

        self.mode_frame.columnconfigure((0, 1), weight=1)

        self.experimental_button = ctk.CTkButton(
            master=self.mode_frame,
            text="Experimental Mode",
            command=lambda: self.switch_mode("experimental")
        )
        self.experimental_button.grid(
            row=0, column=0, padx=10, pady=10, sticky="ew"
        )

        self.automated_button = ctk.CTkButton(
            master=self.mode_frame,
            text="Automated Mode",
            command=lambda: self.switch_mode("automated")
        )
        self.automated_button.grid(
            row=0, column=1, padx=10, pady=10, sticky="ew"
        )





        # CustomTKinter Frames
        self.procedure_queue_frame = ProcedureQueueFrame(
            master = self,
            procedure_handler = self.procedure_handler
        )
        self.procedure_queue_frame.grid(row = 1,
                                        column = 0,
                                        rowspan = 2,
                                        padx = 10,
                                        pady = 10,
                                        sticky = "nsew")
        
        self.camera_frame = CameraFrame(master = self,
                                        dispatcher = self.dispatcher)
        self.camera_frame.grid(row = 1,
                               column = 1,
                               padx = 10,
                               pady = 10,
                               sticky = "nsew")
        
        self.spectrometer_frame = SpectrometerFrame(master = self)
        self.spectrometer_frame.grid(row = 1, column = 0, padx = 10, pady = 10, sticky = "nsew")

    def pause_updates(self):
        """Pause all update loops in this frame"""
        self.camera_frame.pause_video_feed()
    
    def resume_updates(self):
        """Resume all update loops in this frame"""
        self.camera_frame.resume_video_feed()


    def switch_mode(self, mode):
        """Switch between Experimental and Automated modes."""
        self.current_mode = mode
        print(f"Switched to {mode} mode")
