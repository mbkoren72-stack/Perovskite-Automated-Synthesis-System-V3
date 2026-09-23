# Perovskite-Automated-Synthesis-System


## System Guide

This project puts together the software of the PASS system. The application is in Code/src, and Marlin Code sits beside it (because it is essential for the controlboard to function). the CAD files can be found with some of the essential files that are kept here for documentation

## Software Stucture

The main hardware startup path is [Code/src/main.py]. On a real machine it enables `PiGPIOFactory`, builds shared runtime objects, and opens the GUI

The runtime is split into four main layers:

1. [Code/src/core/dispatcher.py] creates and controls the hardware facing objects. This includes the control board, toolhead, camera, spectrometer, hotplate, spin coater, pipette hardware, and gripper hardware.
2. [Code/src/services/move_registry.py]is the command/movement library. It maps procedure step names.
3. [Code/src/services/procedure_handler.py] runs procedures in a background thread
4. [Code/src/gui/app.py] builds the desktop UI and connects it to the shared dispatcher, move registry, and procedure handler.

In practice, the GUI does not directly talk to every device itself. The path goes down through main.

## GUI

- `file_manager`: lets you browse and manage saved files.
- `procedure_builder`: for creating or editing procedures, locations, and obstacle data.
- `procedure_viewer`: queue and run procedures while watching status updates.
- `settings`: device and run-time configuration.
- `aruco_calibration`: camera-based calibration and alignment tools.

## How A Typical Run Works

1. Start the GUI.
2. Connect or verify the required hardware from the UI.
3. Load or build procedure data
4. Run a procedure.
5. Use the Procedure Viewer to verify the outcome of the procedure movement, and use the Kill function if necessary

## Saved Data And Configuration

Multiple parts of the system use YAML or other persisted files under [Code/src/persistant].
`locations.yml` - stores named machine positions.
`obstacles.yml` - stores soft-limit and path-planning obstacles.

## Real Hardware Vs Mock Mode

There are two useful ways to run the GUI:

- Real hardware mode: start [Code/src/main.py]. This path expects the real Linux or Raspberry Pi style hardware environment, including the GPIO-backed servo setup and connected device drivers.
- Mock GUI mode: use [launch_mock_gui.bat], [launch_mock_gui.sh], or [Code/src/gui_mock_launcher.py]. This runs an instance of the GUI independant of the servo and controlboard hardware that causes errors and stops the system from running on a windows laptop. I have NO CLUE if this works on apple computers, but it probably will... I don't know how apple works. 
- To run the Mock GUI, you must change the directory in launc_mock_gui files to your local PASS system directory, or else it will try to run the directory path that its stored in on my computer.

## Repository Layout

- [Code]: Python application, drivers, GUI, and persisted runtime data.
- [Marlin-2.1.2.4]: printer or gantry firmware sources and configuration. (I had no part in making any of this)
- [CAD]: mechanical assemblies and part models.
 
