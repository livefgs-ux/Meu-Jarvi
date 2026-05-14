import os
import platform
import time
import datetime
from pathlib import Path

# Optional dependency
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

# Windows specifics
_IS_WINDOWS = platform.system() == "Windows"

if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    import winreg
else:
    winreg = None
    ctypes = None

def get_known_folders() -> dict:
    """Returns real paths for known folders (best effort)."""
    folders = {
        "home": str(Path.home()),
        "desktop": None,
        "documents": None,
        "downloads": None,
        "pictures": None,
        "videos": None,
        "music": None
    }

    if _IS_WINDOWS:
        try:
            # Query Registry for User Shell Folders
            # This is the most reliable way to find redirected folders (e.g. OneDrive)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                # Mapping of registry keys to our dict keys
                mapping = {
                    "Desktop": "desktop",
                    "Personal": "documents",
                    "{374DE290-123F-4565-9164-39C4925E467B}": "downloads", # Modern Downloads GUID
                    "My Pictures": "pictures",
                    "My Video": "videos",
                    "My Music": "music"
                }
                
                for reg_key, dict_key in mapping.items():
                    try:
                        val, _ = winreg.QueryValueEx(key, reg_key)
                        # Expand environment variables like %USERPROFILE%
                        expanded = os.path.expandvars(val)
                        folders[dict_key] = str(Path(expanded))
                    except FileNotFoundError:
                        pass
        except Exception:
            pass

    # Fallbacks for missing folders
    user_profile = Path.home()
    if not folders["desktop"]: folders["desktop"] = str(user_profile / "Desktop")
    if not folders["documents"]: folders["documents"] = str(user_profile / "Documents")
    if not folders["downloads"]: folders["downloads"] = str(user_profile / "Downloads")
    if not folders["pictures"]: folders["pictures"] = str(user_profile / "Pictures")
    if not folders["videos"]: folders["videos"] = str(user_profile / "Videos")
    if not folders["music"]: folders["music"] = str(user_profile / "Music")

    return folders

def get_running_processes() -> list:
    """Returns a list of running processes (pid, name, exe)."""
    procs = []
    if _HAS_PSUTIL:
        for p in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                info = p.info
                procs.append({
                    "pid": info['pid'],
                    "name": info['name'],
                    "exe": info.get('exe')
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    return procs

def get_active_window_info() -> dict:
    """Returns info about the currently active window (Windows only)."""
    info = {
        "title": None,
        "process_name": None,
        "pid": None,
        "executable": None,
        "status": "unsupported_os"
    }

    if not _IS_WINDOWS:
        return info

    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            info["status"] = "no_active_window"
            return info

        # Get Title
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
        info["title"] = buff.value

        # Get PID
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        info["pid"] = pid.value

        # Get Process Info using psutil if available
        if _HAS_PSUTIL:
            try:
                p = psutil.Process(pid.value)
                info["process_name"] = p.name()
                info["executable"] = p.exe()
                info["status"] = "ok"
            except Exception:
                info["status"] = "partial"
        else:
            info["status"] = "partial_no_psutil"

    except Exception as e:
        info["status"] = f"error: {str(e)}"

    return info

def get_monitor_summary() -> list:
    """Returns a list of monitors (id, primary, width, height)."""
    monitors = []
    if not _IS_WINDOWS:
        return monitors

    try:
        # Define callback for EnumDisplayMonitors
        def monitor_enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
            rect = lprcMonitor.contents
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            
            # Check if primary
            # MONITORINFOEX structure
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)
                ]
            
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if ctypes.windll.user32.GetMonitorInfoW(hMonitor, ctypes.byref(mi)):
                primary = bool(mi.dwFlags & 1) # MONITORINFOF_PRIMARY = 1
            else:
                primary = False

            monitors.append({
                "id": len(monitors),
                "primary": primary,
                "width": width,
                "height": height
            })
            return True

        MonitorEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        callback = MonitorEnumProc(monitor_enum_proc)
        ctypes.windll.user32.EnumDisplayMonitors(None, None, callback, 0)
    except Exception:
        pass

    return monitors

def normalize_app_identity(app_name: str) -> dict:
    """Normalizes human app names to canonical identities."""
    raw = app_name.lower().strip()
    
    mapping = {
        "chrome": "Google Chrome",
        "google chrome": "Google Chrome",
        "edge": "Microsoft Edge",
        "microsoft edge": "Microsoft Edge",
        "internet explorer": "Internet Explorer",
        "ie": "Internet Explorer",
        "explorer": "Windows File Explorer",
        "file explorer": "Windows File Explorer",
        "windows explorer": "Windows File Explorer",
        "vs code": "Visual Studio Code",
        "vscode": "Visual Studio Code",
        "visual studio code": "Visual Studio Code",
        "cursor": "Cursor",
        "steam": "Steam",
        "discord": "Discord"
    }
    
    # Executable mapping
    exe_mapping = {
        "Google Chrome": "chrome.exe",
        "Microsoft Edge": "msedge.exe",
        "Internet Explorer": "iexplore.exe",
        "Windows File Explorer": "explorer.exe",
        "Visual Studio Code": "Code.exe",
        "Cursor": "Cursor.exe",
        "Steam": "steam.exe",
        "Discord": "Discord.exe"
    }

    normalized = mapping.get(raw, app_name)
    return {
        "raw": app_name,
        "normalized": normalized,
        "exe": exe_mapping.get(normalized)
    }

def verify_app_match(requested_app: str, observed: str) -> dict:
    """Checks if the observed app matches the requested one."""
    req = normalize_app_identity(requested_app)
    obs_raw = observed.lower()
    
    # Direct match on normalized name
    if req["normalized"].lower() in obs_raw:
        return {"match": True, "confidence": 1.0, "reason": "name_match"}
    
    # Check executable match
    if req["exe"]:
        if req["exe"].lower() in obs_raw:
            return {"match": True, "confidence": 1.0, "reason": "exe_match"}

    # Special Mismatch Cases
    mismatches = [
        ("Visual Studio Code", ["cursor"]),
        ("Cursor", ["code.exe", "visual studio code"]),
        ("Internet Explorer", ["explorer.exe", "file explorer"]),
        ("Google Chrome", ["msedge.exe", "edge"]),
        ("Microsoft Edge", ["chrome.exe", "google chrome"])
    ]
    
    for req_name, bad_obs in mismatches:
        if req["normalized"] == req_name:
            for bad in bad_obs:
                if bad in obs_raw:
                    return {"match": False, "confidence": 1.0, "reason": f"forbidden_overlap: {req_name} vs {bad}"}

    return {"match": False, "confidence": 0.5, "reason": "no_clear_match"}

def detect_blocking_ui(text_or_title: str) -> dict:
    """Detects blocking UI signals like consent or login screens."""
    raw = text_or_title.lower()
    
    blocks = {
        "consent": ["before you continue", "consent", "cookies", "accept all", "agree"],
        "auth": ["login", "sign in", "password", "authenticate"],
        "security": ["captcha", "robot", "security check"],
        "denial": ["access denied", "permission denied", "blocked", "failed", "forbidden"],
        "system": ["error", "dialog", "update required", "critical"]
    }
    
    for block_type, keywords in blocks.items():
        for kw in keywords:
            if kw in raw:
                return {
                    "detected": True,
                    "type": block_type,
                    "confidence": 0.8 if kw in raw else 0.0,
                    "evidence": kw
                }
                
    return {
        "detected": False,
        "type": None,
        "confidence": 0.0,
        "evidence": None
    }

def build_environment_snapshot() -> dict:
    """Returns a safe read-only snapshot of the environment."""
    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "known_folders": get_known_folders(),
        "active_window": get_active_window_info(),
        "monitors": get_monitor_summary(),
        "running_processes_summary": f"{len(get_running_processes())} processes found",
        "blocking_signals": detect_blocking_ui(get_active_window_info().get("title") or "")
    }
