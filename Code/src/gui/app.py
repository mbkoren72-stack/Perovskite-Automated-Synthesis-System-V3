import customtkinter as ctk
import os
import logging
import tkinter as tk
from time import sleep
from .components.constants import *
from .frames import *
from .frames.splash_frame import SplashFrame

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")

class App(ctk.CTk):
    """Application for Perovskite Automated Synthesis System"""
    def __init__(self, move_registry, dispatcher, procedure_handler, show_splash=True):
        super().__init__(fg_color = FOREGROUND_COLOR)

        self.move_registry = move_registry
        self.dispatcher = dispatcher
        self.procedure_handler = procedure_handler
        self.show_splash = show_splash

        # # If run from main, takes the file path 
        # self.current_directory = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # self.cat_icon_path = os.path.join(self.current_directory, "gui", "icons", "cat.ico")

        # Define the window
        self.title("Perovskite Automated Synthesis System V3")
        # self.iconbitmap(self.cat_icon_path)
        self.geometry("1600x800")

        self.grid_rowconfigure(0, weight = 1)
        self.grid_rowconfigure(1, weight = 0)

        self.grid_columnconfigure(0, weight = 0)
        self.grid_columnconfigure(1, weight = 1)

        self.tab_manager_frame = TabManagerFrame(
            master = self,
            controller = self
        )
        self.tab_manager_frame.grid(row = 0, column = 0, rowspan = 2, padx = 0, pady = 0, sticky = "nsew")
        
        self._right_pane = tk.PanedWindow(self, orient=tk.VERTICAL)

        self._right_pane.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=0, pady=0)

        self.tab_view_frame = TabViewFrame(
            master = self._right_pane, 
            controller = self, 
            dispatcher = self.dispatcher, 
            move_registry = self.move_registry, 
            procedure_handler = self.procedure_handler
        )
        # Add the tab view and info frame to the paned window so the sash can be dragged
        self._right_pane.add(self.tab_view_frame)

        self.info_frame = InfoFrame(
            master = self._right_pane,
            controller = self
        )
        self._right_pane.add(self.info_frame)




        
        # Mode selection screen
        self.mode_selection_frame = ctk.CTkFrame(
            master=self,
            fg_color=BACKGROUND_COLOR,
            corner_radius=0
        )

        self.mode_selection_frame.place(
            relx=0, rely=0, relwidth=1, relheight=1
        )

        erimental_button = ctk.CTkButton(
            master=self.mode_selection_frame,
            text="Experimental",
            width=250,
            height=80,
            command=self.open_experimental
        )
        erimental_button.place(
            relx=0.4, rely=0.5, anchor="center"
        )
        # Experimental Mode description
        self.experimental_description = ctk.CTkLabel(
            master=self.mode_selection_frame,
            text="Manually enter each procedure step\nand test gantry movements.",
            font=ctk.CTkFont(size=15),
            text_color="gray30",
            justify="center"
        )
        self.experimental_description.place(
            relx=0.4, rely=0.59, anchor="center"
        )

        self.automated_button = ctk.CTkButton(
            master=self.mode_selection_frame,
            text="Automated",
            width=250,
            height=80,
            command=self.open_automated
        )
        self.automated_button.place(
            relx=0.6, rely=0.5, anchor="center"
        )
        # Automated Mode description
        self.automated_description = ctk.CTkLabel(
            master=self.mode_selection_frame,
            text="Execute full cycle perovskite \n synthesis (UNDER CONSTRUCTION).",
            font=ctk.CTkFont(size=15),
            text_color="gray30",
            justify="center"
        )
        self.automated_description.place(
            relx=0.6, rely=0.59, anchor="center"
        )


        # Blank Automated page
        self.automated_frame = ctk.CTkFrame(
            master=self,
            fg_color=BACKGROUND_COLOR,
            corner_radius=0
        )

        self.back_button = ctk.CTkButton(
            master=self.automated_frame,
            text="Back",
            command=self.show_mode_selection
        )
        self.back_button.place(x=20, y=20)

        # Back button for Experimental Mode
        self.experimental_back_button = ctk.CTkButton(
            master=self,
            text="Back to Mode Selection",
            width=180,
            command=self.show_mode_selection
        )




        # Ensures the application performs driver cleanup on the  window close 
        try:
            self.protocol("WM_DELETE_WINDOW", self._on_closing)
        except Exception:

            pass

        # Shows a splashscreen on startup when running with the full hardware stack. The text color needs to be changed eventually
        if self.show_splash:
            try:
                self.splash = SplashFrame(master=self, dispatcher=self.dispatcher, move_registry=self.move_registry, controller=self)
                # place to cover entire window and bring to front
                self.splash.place(relx=0, rely=0, relwidth=1, relheight=1)
                try:
                    self.splash.lift()
                except Exception:
                    pass
            except Exception:
                logging.getLogger("Main Logger").exception("Failed to create splash frame")

    def _on_closing(self):
   
        logger = logging.getLogger("Main Logger")
        logger.info("Application closing — scheduling cleanup")

        def _cleanup():
            logger.info("Background cleanup started")

            try:
                if self.procedure_handler:
                    self.procedure_handler.kill(rearm=False, timeout=3.0)
            except Exception:
                logger.exception("Error while killing procedure handler during shutdown")



            try:
                if self.move_registry:
                    self.move_registry.kill()
            except Exception:
                logger.exception("Error while invoking move_registry.kill() during shutdown")


            sleep(0.2)



            try:
                drivers = [
                    'control_board', 'spin_coater', 'camera', 'spectrometer', 'hotplate', 'vial_carousel'
                ]
                for name in drivers:
                    try:
                        drv = getattr(self.dispatcher, name, None)
                        if drv is None:
                            continue
                        if hasattr(drv, 'disconnect') and callable(drv.disconnect):
                            try:
                                drv.disconnect()
                            except Exception:
                                logger.exception(f"Error disconnecting {name}")
                    except Exception:
                        logger.exception(f"Error during shutdown driver cleanup for {name}")
            except Exception:
                logger.exception("Error during driver cleanup")

            logger.info("Background cleanup finished")

        try:
            import threading as _threading
            t = _threading.Thread(target=_cleanup, daemon=True)
            t.start()
        except Exception:
            logger.exception("Failed to start background cleanup thread")

        try:
            self.destroy()
        except Exception:
            pass












    def open_experimental(self):
        """Open existing GUI on the Procedure Builder tab."""
        self.mode_selection_frame.place_forget()
        self.automated_frame.place_forget()

        self.switch_tab("procedure_builder")

        self.experimental_back_button.place(
            relx=0.5, y=10, anchor="n"
        )
        self.experimental_back_button.lift()

    def open_automated(self):
        """Open blank Automated Mode page."""
        self.experimental_back_button.place_forget()
        self.mode_selection_frame.place_forget()

        self.automated_frame.place(
            relx=0, rely=0, relwidth=1, relheight=1
        )
        self.automated_frame.lift()

    def show_mode_selection(self):
        """Return to the mode selection screen."""
        self.experimental_back_button.place_forget()
        self.automated_frame.place_forget()

        self.mode_selection_frame.place(
            relx=0, rely=0, relwidth=1, relheight=1
        )
        self.mode_selection_frame.lift()

    def switch_tab(self, tab_name):
        self.tab_manager_frame.current_tab = tab_name
        self.tab_view_frame.goto_tab(tab_name)

        


if __name__ == "__main__":
    app = App()
    app.mainloop()
        



