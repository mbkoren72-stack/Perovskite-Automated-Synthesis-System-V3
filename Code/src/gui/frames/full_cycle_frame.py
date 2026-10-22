import customtkinter as ctk


class FullCycleFrame(ctk.CTkFrame):
      """
    GUI for configuring and previewing an automated synthesis cycle
    Allows users to enter experiment parameters and run a full cycle 
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.title = ctk.CTkLabel(
            self,
            text="Automated Synthesis",
            font=("Arial", 24, "bold")
        )
        self.title.pack(pady=20)

        # Store user input feilds by name
        self.entries = {}

        # Step by Step what a full cycle is (need to add or move around steps)
        fields = [
            ("Pipette Index (0 or 1)", "pipette"),
            ("Solution Vial", "vial"),
            ("Solution Volume (uL)", "volume"),
            ("Spin Speed (RPM)", "rpm"),
            ("Spin Duration (seconds)", "spin_time"),
            ("Hotplate Temperature (C)", "temperature")
        ]

        # Create a label and input box for each parameter
        for label_text, key in fields:
            label = ctk.CTkLabel(self, text=label_text)
            label.pack(pady=(8, 0))

            entry = ctk.CTkEntry(self, width=250)
            entry.pack(pady=5)

           # Store the input box so its value can be accessed later
            self.entries[key] = entry

        self.generate_button = ctk.CTkButton(
            self,
            text="Generate Procedure Preview",
            command=self.generate_preview
        )
        self.generate_button.pack(pady=20)

       # Text area to display the generated procedure steps
        self.preview = ctk.CTkTextbox(
            self,
            width=500,
            height=200
        )
        self.preview.pack(pady=10)

    def generate_preview(self):

        try:
            pipette = int(self.entries["pipette"].get())
            vial = int(self.entries["vial"].get())
            volume = int(self.entries["volume"].get())
            rpm = int(self.entries["rpm"].get())
            spin_time = int(self.entries["spin_time"].get())
            temperature = int(self.entries["temperature"].get())

          # Check for invalid inputs or fits volume within the pipette
            if pipette not in (0, 1):
                raise ValueError("Pipette index must be 0 or 1")
            if vial < 0 or volume <= 0 or rpm <= 0 or spin_time <= 0:
                raise ValueError("Enter valid positive experiment settings")
            if volume > (200 if pipette == 0 else 1000):
                raise ValueError("Volume exceeds pipette capacity")

            steps = [
                ["set_pipette", pipette],
                ["extract_from_vial", vial, volume],
                ["add_spin_coater_step", rpm, spin_time],
                ["run_spin_coater"],
                ["set_temperature", temperature],
                ["put_away_pipette"]
            ]

            self.preview.delete("1.0", "end")

            for i, step in enumerate(steps, start=1):
                self.preview.insert(
                    "end",
                    f"{i}. {step}\n"
                )

            self.preview.insert(
                "end",
                "\nPREVIEW ONLY - NOT A COMPLETE OR VERIFIED CYCLE"
            )

        except ValueError as e:
            self.preview.delete("1.0", "end")
            self.preview.insert(
                "end",
                f"Invalid input: {e}"
            )
