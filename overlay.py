"""Frameless titanium system-monitor overlay.

Always on top, semi-transparent, dragged with the left mouse button.
Right-click toggles each reading and exits. Stats refresh once per second
from a background thread so the window stays responsive.

Build a windowed executable from this folder:

    powershell -ExecutionPolicy Bypass -File .\build.ps1
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
import time
from ctypes import wintypes
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# DPI awareness has to be set before Tk is created, or the window looks soft.
if os.name == "nt":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import tkinter as tk
from tkinter import messagebox

try:
    import psutil
except ImportError:  # pragma: no cover - handled with a dialog at startup
    psutil = None

try:
    import GPUtil
except ImportError:
    GPUtil = None


# Titanium / metallic gray palette.
BG = "#1c1c1e"
BORDER = "#8e8e93"
DIVIDER = "#8e8e93"
LABEL = "#a1a1a6"
VALUE = "#f2f2f7"
MUTED = "#8e8e93"
BRAND = "#7dbeff"
BRAND_TEXT = "Made by ghost0x7"

ALPHA = 0.92
SAMPLE_MS = 1000
SETTINGS_DIRNAME = "GhostOverlay"

ROW_DEFS = (
    ("cpu", "CPU"),
    ("cpu_temp", "CPU Temp"),
    ("ram", "RAM"),
    ("gpu", "GPU"),
    ("gpu_temp", "GPU Temp"),
)
MENU_LABELS = {
    "cpu": "CPU",
    "cpu_temp": "CPU Temperature",
    "ram": "RAM",
    "gpu": "GPU Usage",
    "gpu_temp": "GPU Temperature",
}

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class _HiddenPopen(subprocess.Popen):
    """Popen that does not flash a console and cannot hang the sampler."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        if os.name == "nt":
            flags = int(kwargs.get("creationflags", 0) or 0)
            kwargs["creationflags"] = flags | _NO_WINDOW
            startup = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[union-attr]
            kwargs["startupinfo"] = startup
        super().__init__(*args, **kwargs)

    def communicate(self, input: Optional[bytes] = None, timeout: Optional[float] = None):  # type: ignore[override]
        try:
            return super().communicate(input=input, timeout=3 if timeout is None else timeout)
        except subprocess.TimeoutExpired:
            self.kill()
            try:
                super().communicate(timeout=1)
            except Exception:
                pass
            raise


_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79
_SPI_GETWORKAREA = 0x0030


def _settings_path() -> Path:
    """Keep settings in APPDATA so a PyInstaller onefile build can write them."""
    root = os.environ.get("APPDATA")
    folder = Path(root) / SETTINGS_DIRNAME if root else Path.home() / ".ghostoverlay"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "settings.json"


def load_settings() -> dict:
    defaults = {
        "x": None,
        "y": None,
        "show": {key: True for key, _label in ROW_DEFS},
    }
    path = _settings_path()
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return defaults
    if not isinstance(saved, dict):
        return defaults
    show = defaults["show"].copy()
    incoming = saved.get("show")
    if isinstance(incoming, dict):
        for key in show:
            if isinstance(incoming.get(key), bool):
                show[key] = incoming[key]
    defaults["show"] = show
    for axis in ("x", "y"):
        value = saved.get(axis)
        if isinstance(value, int):
            defaults[axis] = value
    return defaults


def save_settings(settings: dict) -> None:
    path = _settings_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    temporary.replace(path)


def _finite(value: object) -> Optional[float]:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


@dataclass
class Snapshot:
    ready: bool = False
    cpu: Optional[float] = None
    cpu_temp: Optional[float] = None
    ram_percent: Optional[float] = None
    ram_used: Optional[int] = None
    ram_total: Optional[int] = None
    gpu: Optional[float] = None
    gpu_temp: Optional[float] = None


_READING_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_LHM_URL = "http://127.0.0.1:8085/data.json"
_LHM_LAUNCH_LOCK = threading.Lock()
_LHM_NEXT_LAUNCH = 0.0
_LHM_ASKED_ADMIN = False


_LHM_BUNDLE_VERSION = "0.9.6"
_LHM_CONFIG = """<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <appSettings>
    <add key="runWebServerMenuItem" value="true" />
    <add key="startMinMenuItem" value="true" />
    <add key="minTrayMenuItem" value="true" />
    <add key="minCloseMenuItem" value="true" />
    <add key="listenerIp" value="127.0.0.1" />
    <add key="listenerPort" value="8085" />
  </appSettings>
</configuration>
"""


def _bundled_lhm() -> Optional[Path]:
    """Folder shipped inside the executable."""
    bases = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            bases.append(Path(meipass))
    bases.append(Path(__file__).resolve().parent / "vendor")
    for base in bases:
        candidate = base / "LibreHardwareMonitor"
        if (candidate / "LibreHardwareMonitor.exe").is_file():
            return candidate
    return None


def _lhm_home() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(root) / "LightOverlay" / "LibreHardwareMonitor"


def _install_bundled_lhm() -> Optional[Path]:
    """Copy the bundled monitor into AppData so it can write its own settings."""
    source = _bundled_lhm()
    if source is None:
        return None
    target = _lhm_home()
    exe = target / "LibreHardwareMonitor.exe"
    marker = target / ".bundle-version"
    current = ""
    if marker.is_file():
        try:
            current = marker.read_text(encoding="utf-8").strip()
        except OSError:
            current = ""
    if not exe.is_file() or current != _LHM_BUNDLE_VERSION:
        target.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            if item.name in {"LibreHardwareMonitor.config", ".bundle-version"}:
                continue
            dest = target / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        config = target / "LibreHardwareMonitor.config"
        if not config.is_file():
            config.write_text(_LHM_CONFIG, encoding="utf-8")
        marker.write_text(_LHM_BUNDLE_VERSION, encoding="utf-8")
    return exe if exe.is_file() else None


def _find_lhm() -> Optional[Path]:
    """Prefer the copy shipped with the app, then a monitor beside the exe."""
    installed = _install_bundled_lhm()
    if installed is not None:
        return installed
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    else:
        roots.append(Path(__file__).resolve().parent)
    candidates = []
    for root in roots:
        candidates.append(root / "LibreHardwareMonitor.exe")
        candidates.append(root / "LibreHardwareMonitor" / "LibreHardwareMonitor.exe")
    candidates.append(Path(r"D:\Tools\LibreHardwareMonitor-win\LibreHardwareMonitor.exe"))
    for path in candidates:
        if path.is_file():
            return path
    return None


def _icon_file() -> Optional[Path]:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            bundled = Path(meipass) / "lightoverlay.ico"
            if bundled.is_file():
                return bundled
    local = Path(__file__).resolve().parent / "assets" / "lightoverlay.ico"
    return local if local.is_file() else None


class CpuTemperature:
    """Best-effort CPU temperature.

    Windows does not expose the Ryzen package temperature on its own.
    LibreHardwareMonitor publishes it on a local page, and that reading
    is preferred. psutil and WMI stay as fallbacks.
    """

    def __init__(self) -> None:
        self._readers: List[Callable[[], Optional[float]]] = []
        self._discovered = False
        self._retry_at = 0.0

    def read(self) -> Optional[float]:
        now = time.monotonic()
        # Rediscover only after a miss, so a later hardware monitor is picked
        # up without reconnecting WMI on every successful sample.
        if not self._discovered or now >= self._retry_at:
            self._discover()
            self._discovered = True
            self._retry_at = now + 30.0
        value = self._first()
        if value is None:
            self._retry_at = min(self._retry_at, now + 30.0)
        else:
            self._retry_at = now + 120.0
        return value

    def _first(self) -> Optional[float]:
        for reader in self._readers:
            try:
                value = reader()
            except Exception:
                continue
            if value is not None:
                return value
        return None

    def _discover(self) -> None:
        self._readers = [self._from_lhm_http, self._from_psutil]
        try:
            import wmi  # type: ignore
        except Exception:
            return
        for namespace, kind in (
            (r"root\LibreHardwareMonitor", "hardware"),
            (r"root\OpenHardwareMonitor", "hardware"),
            (r"root\wmi", "acpi"),
        ):
            try:
                service = wmi.WMI(namespace=namespace)
            except Exception:
                continue
            if kind == "acpi":
                self._readers.append(lambda bound=service: self._from_acpi(bound))
            else:
                self._readers.append(lambda bound=service: self._from_hardware_monitor(bound))

    def _ensure_running(self) -> None:
        """Start the bundled sensor app when its local page is down."""
        global _LHM_NEXT_LAUNCH, _LHM_ASKED_ADMIN
        now = time.monotonic()
        with _LHM_LAUNCH_LOCK:
            if now < _LHM_NEXT_LAUNCH:
                return
            exe = _find_lhm()
            if exe is None:
                return
            _LHM_NEXT_LAUNCH = now + 15.0
            if psutil is not None:
                try:
                    for proc in psutil.process_iter(["name"]):
                        if (proc.info.get("name") or "").lower() == "librehardwaremonitor.exe":
                            return
                except Exception:
                    return
            ready_flag = exe.parent / ".sensor-ready"
            if os.name == "nt" and not _LHM_ASKED_ADMIN and not ready_flag.is_file():
                _LHM_ASKED_ADMIN = True
                try:
                    started = ctypes.windll.shell32.ShellExecuteW(
                        None, "runas", str(exe), "", str(exe.parent), 7
                    )
                except Exception:
                    started = 0
                if int(started) > 32:
                    return
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 7  # minimized, without stealing focus
            try:
                subprocess.Popen(
                    [str(exe)],
                    cwd=str(exe.parent),
                    startupinfo=startup,
                )
            except Exception:
                return

    def _from_lhm_http(self) -> Optional[float]:
        try:
            with urllib.request.urlopen(_LHM_URL, timeout=0.6) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except Exception:
            self._ensure_running()
            return None
        found: List[float] = []

        def walk(node: object, trail: str) -> None:
            if not isinstance(node, dict):
                return
            text = str(node.get("Text") or "")
            blob = f"{trail} {text}".lower()
            kind = str(node.get("Type") or "")
            if kind == "Temperature" and "gpu" not in blob and "nvidia" not in blob:
                match = _READING_NUMBER.search(str(node.get("Value") or ""))
                current = _finite(match.group(0)) if match else None
                cpu_sensor = "tctl" in blob or "tdie" in blob or "package" in blob
                if current is not None and 1.0 <= current <= 125.0 and cpu_sensor:
                    found.append(current)
            for child in node.get("Children") or []:
                walk(child, blob)

        walk(payload, "")
        if not found:
            return None
        try:
            located = _find_lhm()
            if located is not None:
                (located.parent / ".sensor-ready").write_text("ok", encoding="utf-8")
        except OSError:
            pass
        return max(found)

    @staticmethod
    def _from_psutil() -> Optional[float]:
        if psutil is None or not hasattr(psutil, "sensors_temperatures"):
            return None
        try:
            groups = psutil.sensors_temperatures() or {}
        except Exception:
            return None
        package: List[float] = []
        cores: List[float] = []
        for name, entries in groups.items():
            blob = str(name).lower()
            for entry in entries:
                current = _finite(getattr(entry, "current", None))
                label = str(getattr(entry, "label", "") or "").lower()
                if current is None or not 1.0 <= current <= 125.0:
                    continue
                text = f"{blob} {label}"
                if "gpu" in text:
                    continue
                if "package" in text or "tctl" in text or "tdie" in text:
                    package.append(current)
                elif "cpu" in text or "core" in text:
                    cores.append(current)
        if package:
            return max(package)
        if cores:
            return max(cores)
        return None

    @staticmethod
    def _from_hardware_monitor(service: object) -> Optional[float]:
        package: List[float] = []
        cores: List[float] = []
        for sensor in service.Sensor():  # type: ignore[attr-defined]
            if str(getattr(sensor, "SensorType", "")) != "Temperature":
                continue
            name = str(getattr(sensor, "Name", "") or "")
            parent = str(getattr(sensor, "Parent", "") or "")
            text = f"{name} {parent}".lower()
            if "gpu" in text:
                continue
            current = _finite(getattr(sensor, "Value", None))
            if current is None or not 1.0 <= current <= 125.0:
                continue
            if "package" in text or "tctl" in text or "tdie" in text:
                package.append(current)
            elif "cpu" in text or "core" in text:
                cores.append(current)
        if package:
            return max(package)
        if cores:
            return max(cores)
        return None

    @staticmethod
    def _from_acpi(service: object) -> Optional[float]:
        found: List[float] = []
        for zone in service.MSAcpi_ThermalZoneTemperature():  # type: ignore[attr-defined]
            raw = _finite(getattr(zone, "CurrentTemperature", None))
            if raw is None:
                continue
            celsius = raw / 10.0 - 273.15
            if 15.0 <= celsius <= 105.0:
                found.append(celsius)
        return max(found) if found else None


class GpuReader:
    """NVIDIA load and temperature via GPUtil, then a silent nvidia-smi query."""

    def __init__(self) -> None:
        self._disabled_until = 0.0
        self._last: Tuple[Optional[float], Optional[float]] = (None, None)
        self._exe: Optional[str] = None
        self._exe_checked = False

    def read(self) -> Tuple[Optional[float], Optional[float]]:
        now = time.monotonic()
        if now < self._disabled_until:
            return self._last
        try:
            reading = self._via_gputil()
            if reading is None or reading == (None, None):
                reading = self._via_nvidia_smi()
        except Exception:
            reading = None
        if reading is None or reading == (None, None):
            # Keep the last good pair so one failed driver query does not flash N/A.
            self._disabled_until = now + 15.0
            return self._last
        self._last = reading
        self._disabled_until = 0.0
        return reading

    def _via_gputil(self) -> Optional[Tuple[Optional[float], Optional[float]]]:
        if GPUtil is None:
            return None
        # GPUtil binds Popen at import time and does not hide the console.
        owner = GPUtil if hasattr(GPUtil, "Popen") else subprocess
        original = getattr(owner, "Popen")
        setattr(owner, "Popen", _HiddenPopen)
        try:
            gpus = GPUtil.getGPUs()
        except Exception:
            return None
        finally:
            setattr(owner, "Popen", original)
        if not gpus:
            return None
        gpu = gpus[0]
        load = _finite(getattr(gpu, "load", None))
        if load is not None and load <= 1.0:
            load *= 100.0
        if load is not None:
            load = min(100.0, max(0.0, load))
        temp = _finite(getattr(gpu, "temperature", None))
        if temp is not None and not 0.0 <= temp <= 125.0:
            temp = None
        return load, temp

    def _via_nvidia_smi(self) -> Optional[Tuple[Optional[float], Optional[float]]]:
        exe = self._resolve_exe()
        if not exe:
            return None
        command = [
            exe,
            "--query-gpu=utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
        kwargs: Dict[str, object] = {
            "args": command,
            "capture_output": True,
            "text": True,
            "timeout": 3,
            "encoding": "utf-8",
            "errors": "replace",
            "check": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = _NO_WINDOW
        completed = subprocess.run(**kwargs)  # type: ignore[arg-type]
        if completed.returncode != 0:
            return None
        line = (completed.stdout or "").strip().splitlines()
        if not line:
            return None
        parts = [part.strip() for part in line[0].split(",")]
        if len(parts) < 2:
            return None
        load = _finite(parts[0])
        temp = _finite(parts[1])
        if load is not None:
            load = min(100.0, max(0.0, load))
        if temp is not None and not 0.0 <= temp <= 125.0:
            temp = None
        if load is None and temp is None:
            return None
        return load, temp

    def _resolve_exe(self) -> Optional[str]:
        if self._exe_checked:
            return self._exe
        self._exe_checked = True
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        drive = os.environ.get("SystemDrive", "C:")
        candidates = [
            "nvidia-smi",
            str(Path(system_root) / "System32" / "nvidia-smi.exe"),
            str(Path(drive) / "Program Files" / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"),
        ]
        for candidate in candidates:
            try:
                kwargs: Dict[str, object] = {
                    "args": [candidate, "-L"],
                    "capture_output": True,
                    "timeout": 3,
                    "check": False,
                }
                if os.name == "nt":
                    kwargs["creationflags"] = _NO_WINDOW
                completed = subprocess.run(**kwargs)  # type: ignore[arg-type]
            except (OSError, subprocess.TimeoutExpired):
                continue
            if completed.returncode == 0:
                self._exe = candidate
                return candidate
        return None


class HardwareReader:
    def __init__(self) -> None:
        self._temps = CpuTemperature()
        self._gpu = GpuReader()

    def prime(self) -> None:
        """First cpu_percent() call only starts the sampling window."""
        if psutil is None:
            return
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            return

    def read(self) -> Snapshot:
        cpu = self._cpu()
        ram_percent, ram_used, ram_total = self._ram()
        try:
            gpu, gpu_temp = self._gpu.read()
        except Exception:
            gpu, gpu_temp = None, None
        try:
            cpu_temp = self._temps.read()
        except Exception:
            cpu_temp = None
        return Snapshot(
            ready=True,
            cpu=cpu,
            cpu_temp=cpu_temp,
            ram_percent=ram_percent,
            ram_used=ram_used,
            ram_total=ram_total,
            gpu=gpu,
            gpu_temp=gpu_temp,
        )

    def _cpu(self) -> Optional[float]:
        if psutil is None:
            return None
        try:
            value = _finite(psutil.cpu_percent(interval=None))
        except Exception:
            return None
        if value is None:
            return None
        return min(100.0, max(0.0, value))

    def _ram(self) -> Tuple[Optional[float], Optional[int], Optional[int]]:
        if psutil is None:
            return None, None, None
        try:
            memory = psutil.virtual_memory()
            percent = _finite(memory.percent)
            used = int(memory.used)
            total = int(memory.total)
        except Exception:
            return None, None, None
        if percent is not None:
            percent = min(100.0, max(0.0, percent))
        return percent, used, total


class StatsCollector(threading.Thread):
    """Samples hardware off the Tk thread and publishes the latest snapshot."""

    def __init__(self) -> None:
        super().__init__(name="StatsCollector", daemon=True)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._snapshot = Snapshot()
        self._reader = HardwareReader()

    def snapshot(self) -> Snapshot:
        with self._lock:
            return replace(self._snapshot)

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        pythoncom = None
        try:
            import pythoncom as pythoncom_module

            pythoncom_module.CoInitialize()
            pythoncom = pythoncom_module
        except Exception:
            pythoncom = None
        try:
            self._reader.prime()
            # The first cpu_percent() result is meaningless, so wait one interval.
            if self._stop.wait(1.0):
                return
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    latest = self._reader.read()
                except Exception:
                    latest = Snapshot(ready=True)
                with self._lock:
                    self._snapshot = latest
                remaining = 1.0 - (time.monotonic() - started)
                if self._stop.wait(max(0.05, remaining)):
                    break
        finally:
            if pythoncom is not None:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass


def _work_area() -> Tuple[int, int, int, int]:
    if os.name == "nt":
        rect = wintypes.RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        )
        if ok:
            return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, 1280, 800


def _virtual_screen() -> Optional[Tuple[int, int, int, int]]:
    if os.name != "nt":
        return None
    user32 = ctypes.windll.user32
    width = int(user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN))
    height = int(user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN))
    if width <= 0 or height <= 0:
        return None
    return (
        int(user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)),
        width,
        height,
    )


def _apply_tool_window(window: tk.Tk) -> None:
    """Drop the taskbar button so the overlay stays out of the way."""
    if os.name != "nt":
        return
    user32 = ctypes.windll.user32
    user32.GetParent.restype = ctypes.c_void_p
    user32.GetParent.argtypes = [ctypes.c_void_p]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    user32.SetWindowPos.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
    if not hwnd:
        return
    style = user32.GetWindowLongW(hwnd, -20)
    style = (style & ~0x00040000) | 0x00000080  # remove APPWINDOW, add TOOLWINDOW
    user32.SetWindowLongW(hwnd, -20, style)
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)


class OverlayApp:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.collector = StatsCollector()
        self._closed = False
        self._after_id: Optional[str] = None
        self._ticks = 0
        self._drag_origin: Optional[Tuple[int, int]] = None

        self.root = tk.Tk()
        self.root.title("Light Overlay")
        icon = _icon_file()
        if icon is not None:
            try:
                self.root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.0)
        self.root.resizable(False, False)
        self.root.configure(bg=BORDER, highlightthickness=0, bd=0)

        body = tk.Frame(self.root, bg=BG, highlightthickness=0, bd=0)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        self.pad = tk.Frame(body, bg=BG, highlightthickness=0, bd=0)
        self.pad.pack(fill="both", expand=True, padx=8, pady=4)

        self.brand = tk.Label(
            self.pad,
            text=BRAND_TEXT,
            bg=BG,
            fg=BRAND,
            font=("Segoe UI", 7),
            anchor="center",
        )
        self.brand.grid(row=0, column=0, columnspan=4, sticky="ew")

        self.divider = tk.Frame(self.pad, bg=BG, height=1, highlightthickness=0, bd=0)
        self.divider.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(2, 2))
        tk.Frame(self.divider, bg=DIVIDER, height=1, highlightthickness=0, bd=0).pack(fill="x")

        self.flags: Dict[str, tk.BooleanVar] = {}
        self.rows: Dict[str, Tuple[tk.Label, ...]] = {}
        label_font = ("Segoe UI", 8)
        value_font = ("Segoe UI", 8, "bold")

        def _cell(text: str, font: tuple, color: str) -> tk.Label:
            return tk.Label(self.pad, text=text, bg=BG, fg=color, font=font, anchor="w")

        cpu_name = _cell("CPU", label_font, LABEL)
        cpu_value = _cell("—", value_font, MUTED)
        cpu_temp = _cell("—", value_font, MUTED)
        gpu_name = _cell("GPU", label_font, LABEL)
        gpu_value = _cell("—", value_font, MUTED)
        gpu_temp = _cell("—", value_font, MUTED)
        ram_name = _cell("RAM", label_font, LABEL)
        ram_value = _cell("—", value_font, MUTED)

        cpu_name.grid(row=2, column=0, sticky="w")
        cpu_value.grid(row=2, column=1, sticky="w", padx=(4, 8))
        cpu_temp.grid(row=2, column=2, sticky="w")
        gpu_name.grid(row=3, column=0, sticky="w", pady=(1, 0))
        gpu_value.grid(row=3, column=1, sticky="w", padx=(4, 8), pady=(1, 0))
        gpu_temp.grid(row=3, column=2, sticky="w", pady=(1, 0))
        ram_name.grid(row=4, column=0, sticky="w", pady=(1, 0))
        ram_value.grid(row=4, column=1, columnspan=2, sticky="w", padx=(4, 0), pady=(1, 0))

        self.rows = {
            "cpu": (cpu_name, cpu_value),
            "cpu_temp": (cpu_temp,),
            "ram": (ram_name, ram_value),
            "gpu": (gpu_name, gpu_value),
            "gpu_temp": (gpu_temp,),
        }
        for key, _title in ROW_DEFS:
            self.flags[key] = tk.BooleanVar(value=bool(self.settings["show"].get(key, True)))
            self.flags[key].trace_add("write", self._on_toggle)

        self.menu = tk.Menu(
            self.root,
            tearoff=0,
            bg="#242426",
            fg=VALUE,
            activebackground="#3a3a3c",
            activeforeground=BRAND,
            activeborderwidth=0,
            bd=0,
            font=("Segoe UI", 9),
        )
        for key, _title in ROW_DEFS:
            self.menu.add_checkbutton(
                label=MENU_LABELS[key],
                variable=self.flags[key],
                onvalue=True,
                offvalue=False,
            )
        self.menu.add_separator()
        self.menu.add_command(label="Exit", command=self.close)

        self._apply_visibility()
        self._bind_chrome(self.pad)
        self.root.bind("<Escape>", lambda _event: self.close())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.update_idletasks()
        self._place_initial()
        _apply_tool_window(self.root)
        self.root.attributes("-alpha", ALPHA)
        self.root.attributes("-topmost", True)

    def run(self) -> None:
        self.collector.start()
        try:
            self._tick()
            self.root.mainloop()
        finally:
            self.collector.stop()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._save_settings()
        except Exception:
            pass
        self.collector.stop()
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _bind_chrome(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._press, add="+")
        widget.bind("<B1-Motion>", self._drag, add="+")
        widget.bind("<ButtonRelease-1>", self._release, add="+")
        widget.bind("<Button-3>", self._popup, add="+")
        try:
            widget.configure(cursor="fleur")
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._bind_chrome(child)

    def _press(self, event: tk.Event) -> None:
        self._drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        if self._drag_origin is None:
            return
        x = event.x_root - self._drag_origin[0]
        y = event.y_root - self._drag_origin[1]
        self.root.geometry(f"+{x}+{y}")

    def _release(self, _event: tk.Event) -> None:
        self._drag_origin = None
        try:
            self._save_settings()
        except Exception:
            pass

    def _popup(self, event: tk.Event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.menu.grab_release()
            except tk.TclError:
                pass

    def _on_toggle(self, *_args: object) -> None:
        if self._closed:
            return
        self._apply_visibility()
        try:
            self._save_settings()
        except Exception:
            pass

    def _apply_visibility(self) -> None:
        any_visible = False
        for key, widgets in self.rows.items():
            visible = self.flags[key].get()
            any_visible = any_visible or visible
            for widget in widgets:
                if visible:
                    widget.grid()
                else:
                    widget.grid_remove()
        if any_visible:
            self.divider.grid()
        else:
            self.divider.grid_remove()
        try:
            self.root.update_idletasks()
        except tk.TclError:
            pass

    def _place_initial(self) -> None:
        saved_x = self.settings.get("x")
        saved_y = self.settings.get("y")
        if isinstance(saved_x, int) and isinstance(saved_y, int):
            x, y = self._clamp(saved_x, saved_y)
        else:
            left, top, right, _bottom = _work_area()
            width = self.root.winfo_width()
            x, y = self._clamp(right - width - 18, top + 18)
            if x < left:
                x = left + 18
        self.root.geometry(f"+{x}+{y}")

    def _clamp(self, x: int, y: int) -> Tuple[int, int]:
        self.root.update_idletasks()
        width = max(self.root.winfo_width(), 48)
        height = max(self.root.winfo_height(), 24)
        virtual = _virtual_screen()
        if virtual is None:
            return x, y
        origin_x, origin_y, span_w, span_h = virtual
        min_x = origin_x - width + 48
        max_x = origin_x + span_w - 48
        min_y = origin_y - height + 48
        max_y = origin_y + span_h - 48
        if min_x > max_x or min_y > max_y:
            return x, y
        return min(max(x, min_x), max_x), min(max(y, min_y), max_y)

    def _save_settings(self) -> None:
        self.settings = {
            "x": int(self.root.winfo_x()),
            "y": int(self.root.winfo_y()),
            "show": {key: bool(var.get()) for key, var in self.flags.items()},
        }
        save_settings(self.settings)

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            self._render(self.collector.snapshot())
            self._ticks += 1
            if self._ticks % 5 == 0:
                self.root.attributes("-topmost", True)
        except tk.TclError:
            return
        except Exception:
            pass
        if not self._closed:
            self._after_id = self.root.after(SAMPLE_MS, self._tick)

    def _render(self, snap: Snapshot) -> None:
        self._set_reading("cpu", *_percent(snap.ready, snap.cpu))
        self._set_reading("cpu_temp", *_temp(snap.ready, snap.cpu_temp))
        self._set_reading("ram", *_ram(snap))
        self._set_reading("gpu", *_percent(snap.ready, snap.gpu))
        self._set_reading("gpu_temp", *_temp(snap.ready, snap.gpu_temp))

    def _set_reading(self, key: str, text: str, color: str) -> None:
        widget = self.rows[key][-1]
        if widget.cget("text") != text or str(widget.cget("fg")) != color:
            widget.configure(text=text, fg=color)


def _percent(ready: bool, value: Optional[float]) -> Tuple[str, str]:
    if not ready:
        return "—", MUTED
    if value is None:
        return "N/A", MUTED
    return f"{value:.0f}%", VALUE


def _temp(ready: bool, value: Optional[float]) -> Tuple[str, str]:
    if not ready:
        return "—", MUTED
    if value is None:
        return "N/A", MUTED
    return f"{value:.0f}°C", VALUE


def _ram(snap: Snapshot) -> Tuple[str, str]:
    if not snap.ready:
        return "—", MUTED
    if snap.ram_percent is None or snap.ram_used is None or not snap.ram_total:
        return "N/A", MUTED
    return f"{snap.ram_percent:.0f}%", VALUE


def main() -> None:
    if psutil is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Light Overlay",
            "Missing dependency: psutil\n\nInstall it with:\npip install psutil",
        )
        root.destroy()
        raise SystemExit(1)
    try:
        CpuTemperature()._ensure_running()
    except Exception:
        pass
    OverlayApp().run()


if __name__ == "__main__":
    main()
