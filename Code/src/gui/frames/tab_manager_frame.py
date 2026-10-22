import customtkinter as ctk
from PIL import Image

from ..components.constants import *

class TabManagerFrame(ctk.CTkFrame):
    """Frame for Displaying different tab options"""
    def __init__(self, master, controller, **kwargs):
        super().__init__(
            master,
            width = 70,
            height = 800,
            corner_radius = 0,
            fg_color = FOREGROUND_COLOR
        )

        self.controller = controller   

        self.current_tab = "file_manager"

        self.rowconfigure(4, weight = 1)
        self.columnconfigure(0, weight = 0)
        # Define all Tab Icons
        self.unselected_file_image = self.path_to_ctk_image("gui/icons/unselected_file.png")
        self.selected_file_image = self.path_to_ctk_image("gui/icons/selected_file.png")

        self.unselected_builder_image = self.path_to_ctk_image("gui/icons/unselected_builder.png")
        self.selected_builder_image = self.path_to_ctk_image("gui/icons/selected_builder.png")

        self.unselected_procedure_image = self.path_to_ctk_image("gui/icons/unselected_procedure.png")
        self.selected_procedure_image = self.path_to_ctk_image("gui/icons/selected_procedure.png")

        self.unselected_settings_image = self.path_to_ctk_image("gui/icons/unselected_settings.png")
        self.selected_settings_image = self.path_to_ctk_image("gui/icons/selected_settings.png")

        self.unselected_calibration_image = self.path_to_ctk_image("gui/icons/unselected_calibration.png")  # Reuse settings icon for now
        self.selected_calibration_image = self.path_to_ctk_image("gui/icons/selected_calibration.png")      # Reuse settings icon for now

        # File tab button
        self.file_tab_button = ctk.CTkButton(
            master = self,
            width = 70, 
            height = 70, 
            corner_radius = 0,
            fg_color = FOREGROUND_COLOR,
            hover_color = FOREGROUND_COLOR,
            image = self.unselected_file_image,
            text = "",
            command = lambda: self.controller.switch_tab("file_manager") 
        )

        self.file_tab_button.grid(row = 0, column = 0, padx = 0, pady = 0, sticky = "new") # Establishes grid placement
        self.frame_image_bindings(self.file_tab_button, self.unselected_file_image, self.selected_file_image) #Binds the hover actions to file icon replacement


        # Builder tab button
        self.builder_tab_button = ctk.CTkButton(
            master = self,
            width = 70, 
            height = 70, 
            corner_radius = 0,
            fg_color = FOREGROUND_COLOR,
            hover_color = FOREGROUND_COLOR,
            image = self.unselected_builder_image,
            text = "",
            command = lambda: self.controller.switch_tab("procedure_builder") 
        )
        self.builder_tab_button.grid(row = 1, column = 0, padx = 0, pady = 0, sticky = "new") # Establishes grid placement
        self.frame_image_bindings(self.builder_tab_button, self.unselected_builder_image, self.selected_builder_image) #Binds the hover actions to file icon replacement

        # Builder tab button
        self.procedure_tab_button = ctk.CTkButton(
            master = self,
            width = 70, 
            height = 70, 
            corner_radius = 0,
            fg_color = FOREGROUND_COLOR,
            hover_color = FOREGROUND_COLOR,
            image = self.unselected_procedure_image,
            text = "",
            command = lambda: self.controller.switch_tab("procedure_viewer") 
        )
        self.procedure_tab_button.grid(row = 2, column = 0, padx = 0, pady = 0, sticky = "new") # Establishes grid placement
        self.frame_image_bindings(self.procedure_tab_button, self.unselected_procedure_image, self.selected_procedure_image) #Binds the hover actions to file icon replacement

        self.settings_tab_button = ctk.CTkButton(
            master = self,
            width = 70, 
            height = 70, 
            corner_radius = 0,
            fg_color = FOREGROUND_COLOR,
            hover_color = FOREGROUND_COLOR,
            image = self.unselected_settings_image,
            text = "",
            command = lambda: self.controller.switch_tab("settings") 
        )
        self.settings_tab_button.grid(row = 5, column = 0, padx = 0, pady = 0, sticky = "sew")
        self.frame_image_bindings(self.settings_tab_button, self.unselected_settings_image, self.selected_settings_image) #Binds the hover actions to file icon replacement

        # Full Cycle tab button, add icons later 
        self.full_cycle_tab_button = ctk.CTkButton(
            master = self,
            width = 70,
            height = 70,
            corner_radius = 0,
            fg_color = FOREGROUND_COLOR,
            hover_color = FOREGROUND_COLOR,
            text = "Full\nCycle",
            font = ("Arial", 13, "bold"),
            command = lambda: self.controller.switch_tab("full_cycle")
        )

        # Place the Full Cycle button under Procedure Viewer
        self.full_cycle_tab_button.grid(
            row = 3,
            column = 0,
            padx = 0,
            pady = 0,
            sticky = "new"
        )
        # Calibration tab button (ArUco marker calibration)
        self.calibration_tab_button = ctk.CTkButton(
            master = self,
            width = 70, 
            height = 70, 
            corner_radius = 0,
            fg_color = FOREGROUND_COLOR,
            hover_color = FOREGROUND_COLOR,
            image = self.unselected_calibration_image,
            text = "",
            command = lambda: self.controller.switch_tab("aruco_calibration") 
        )
        self.calibration_tab_button.grid(row = 6, column = 0, padx = 0, pady = 0, sticky = "sew")
        self.frame_image_bindings(self.calibration_tab_button, self.unselected_calibration_image, self.selected_calibration_image)
        
        # Binds buttons on bottom to dissapear when tab selection buttons collide
        self.master.bind(
            "<Configure>",
            lambda e: self.hide_overlapping_frames(
                disp_frame = self.full_cycle_tab_button,
                hide_frame = self.settings_tab_button
            )
        )

        # self.frame_exclusive_color_bindings(self.file_tab_button, self.procedure_tab_button, self.builder_tab_button)

    def hide_overlapping_frames(self, disp_frame = None, hide_frame = None, event=None):
        if disp_frame is None or hide_frame is None:
            return

        try:
            if not self.winfo_exists() or not disp_frame.winfo_exists() or not hide_frame.winfo_exists():
                return

            self.update_idletasks()

            required_height = (
                disp_frame.winfo_reqheight() +
                hide_frame.winfo_reqheight() +
                210 # This number determines how far from the top the frame "collision" is detected. Higher number = sooner collision
            )

            if self.winfo_height() < required_height:
                hide_frame.grid_remove()
            else:
                if not hide_frame.winfo_ismapped():
                    hide_frame.grid()
        except Exception:
            return
    
    def path_to_ctk_image(self, image_path):
        if image_path is None:
            raise ValueError("image_path must be provided")

        return ctk.CTkImage(
            light_image=Image.open(image_path),
            dark_image=Image.open(image_path),
            size=(55, 55)
        )
    
    def frame_image_bindings(self, widget, image_normal, image_hover):
        widget.bind("<Enter>", lambda e: widget.configure(image=image_hover))
        widget.bind("<Leave>", lambda e: widget.configure(image=image_normal))

    # def frame_exclusive_color_bindings(self, widget_one, widget_two, widget_three):
    #     widget_one.bind("<Button>", lambda e: [
    #         widget_one.configure(fg_color = BACKGROUND_COLOR),
    #         widget_two.configure(fg_color = FOREGROUND_COLOR),
    #         widget_three.configure(fg_color = FOREGROUND_COLOR)
    #     ])

    #     widget_two.bind("<Button>", lambda e: [
    #         widget_two.configure(fg_color = BACKGROUND_COLOR),
    #         widget_three.configure(fg_color = FOREGROUND_COLOR),
    #         widget_one.configure(fg_color = FOREGROUND_COLOR)
    #     ])

    #     widget_three.bind("<Button>", lambda e: [
    #         widget_three.configure(fg_color = BACKGROUND_COLOR),
    #         widget_one.configure(fg_color = FOREGROUND_COLOR),
    #         widget_two.configure(fg_color = FOREGROUND_COLOR)
    #     ])

    def set_next_tab(self, tab):
        if self.current_tab == tab:
            print("Tab Already Set!")
            return
        if not(tab in TABS):
            raise TypeError("tab does not exist")

        self.current_tab = tab
        print("next tab set: " + self.current_tab )

