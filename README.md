# Light Overlay

A small, always-on-top window for live system stats:

- CPU usage
- CPU temperature
- RAM usage
- NVIDIA GPU usage
- NVIDIA GPU temperature

Drag the window with the left mouse button. Right-click to show or hide any reading, or to exit.

## Run

Launch:

`LightOverlay.exe`

Python is not required.

## CPU temperature

Windows does not expose AMD CPU temperature to normal apps. GPU temperature works on its own because the NVIDIA driver is always running. CPU temperature needs LibreHardwareMonitor.

1. Open the releases page:

https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/latest

2. Download the file named:

`LibreHardwareMonitor.zip`

3. Do not download the file with `NET.10` in its name. That build requires .NET 10, and Windows will keep saying .NET is missing even after you install a different version.

4. Extract the zip. The regular build runs on .NET Framework 4.8, which is already included with Windows 10 and Windows 11.

5. The first time, right-click `LibreHardwareMonitor.exe` and choose **Run as administrator**.

6. In the menu, open **Options**, then **Remote Web Server**, and turn **Run** on.

Leave the port at `8085`.

7. Keep LibreHardwareMonitor running in the background. You can minimize it. If you quit it completely, CPU temperature in Light Overlay goes back to `N/A`.

If `LibreHardwareMonitor.exe` sits next to `LightOverlay.exe`, or inside a `LibreHardwareMonitor` folder next to the app, Light Overlay will try to start it when the temperature is unavailable.

## Build from source

```powershell
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name LightOverlay overlay.py
```

The executable is created at:

`dist\LightOverlay.exe`
