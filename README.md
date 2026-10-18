# Light Overlay

A small, always-on-top window for live system stats:

- CPU usage
- CPU temperature
- RAM usage
- NVIDIA GPU usage
- NVIDIA GPU temperature

Drag the window with the left mouse button. Right-click to show or hide any reading, or to exit.


<img width="1919" height="1032" alt="Screenshot 2026-10-18 125528" src="https://github.com/user-attachments/assets/2b765493-6411-49c0-bd18-3b461ab7151c" />



## Run

Launch:

`LightOverlay.exe`

Python is not required.

## CPU temperature

GPU temperature works immediately. The NVIDIA driver is already running.

CPU temperature is included. `LightOverlay.exe` carries LibreHardwareMonitor and starts it in the background. You do not download or configure that program yourself.

The first time Windows opens it, accept the administrator prompt. That lets the CPU sensor load. After that, Light Overlay starts the monitor on its own. If you quit LibreHardwareMonitor completely, CPU temperature goes back to `N/A` until you open Light Overlay again.

LibreHardwareMonitor is included under the Mozilla Public License 2.0. Its project page is https://github.com/LibreHardwareMonitor/LibreHardwareMonitor.

## Build from source

```powershell
python -m pip install -r requirements.txt pyinstaller pillow
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

The executable is created at:

`dist\LightOverlay.exe`
