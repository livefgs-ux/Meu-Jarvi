import os
import time
import subprocess
import platform
import shutil
from core.environment_state import get_active_window_info, verify_app_match
from core.app_inventory import resolve_trusted_app, format_app_resolution_message

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

_SYSTEM = platform.system()

_APP_ALIASES: dict[str, dict[str, str]] = {

    "chrome":             {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "google chrome":      {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "firefox":            {"Windows": "firefox",                 "Darwin": "Firefox",              "Linux": "firefox"},
    "edge":               {"Windows": "msedge",                  "Darwin": "Microsoft Edge",       "Linux": "microsoft-edge"},
    "brave":              {"Windows": "brave",                   "Darwin": "Brave Browser",        "Linux": "brave-browser"},
    "safari":             {"Windows": "msedge",                  "Darwin": "Safari",               "Linux": "firefox"},
    "opera":              {"Windows": "opera",                   "Darwin": "Opera",                "Linux": "opera"},
    "whatsapp":           {"Windows": "WhatsApp",                "Darwin": "WhatsApp",             "Linux": "whatsapp"},
    "telegram":           {"Windows": "Telegram",                "Darwin": "Telegram",             "Linux": "telegram"},
    "discord":            {"Windows": "Discord",                 "Darwin": "Discord",              "Linux": "discord"},
    "slack":              {"Windows": "Slack",                   "Darwin": "Slack",                "Linux": "slack"},
    "zoom":               {"Windows": "Zoom",                    "Darwin": "zoom.us",              "Linux": "zoom"},
    "teams":              {"Windows": "msteams",                 "Darwin": "Microsoft Teams",      "Linux": "teams"},
    "skype":              {"Windows": "skype",                   "Darwin": "Skype",                "Linux": "skype"},
    "signal":             {"Windows": "signal",                  "Darwin": "Signal",               "Linux": "signal"},
    "spotify":            {"Windows": "Spotify",                 "Darwin": "Spotify",              "Linux": "spotify"},
    "vlc":                {"Windows": "vlc",                     "Darwin": "VLC",                  "Linux": "vlc"},
    "netflix":            {"Windows": "Netflix",                 "Darwin": "Netflix",              "Linux": "firefox"},
    "vscode":             {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "vs code":            {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "visual studio code": {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "code":               {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "terminal":           {"Windows": "wt",                      "Darwin": "Terminal",             "Linux": "gnome-terminal"},
    "cmd":                {"Windows": "cmd.exe",                 "Darwin": "Terminal",             "Linux": "bash"},
    "powershell":         {"Windows": "powershell.exe",          "Darwin": "Terminal",             "Linux": "bash"},
    "postman":            {"Windows": "Postman",                 "Darwin": "Postman",              "Linux": "postman"},
    "git":                {"Windows": "git-bash",                "Darwin": "Terminal",             "Linux": "bash"},
    "figma":              {"Windows": "Figma",                   "Darwin": "Figma",                "Linux": "figma"},
    "blender":            {"Windows": "blender",                 "Darwin": "Blender",              "Linux": "blender"},
    "word":               {"Windows": "winword",                 "Darwin": "Microsoft Word",       "Linux": "libreoffice --writer"},
    "excel":              {"Windows": "excel",                   "Darwin": "Microsoft Excel",      "Linux": "libreoffice --calc"},
    "powerpoint":         {"Windows": "powerpnt",                "Darwin": "Microsoft PowerPoint", "Linux": "libreoffice --impress"},
    "libreoffice":        {"Windows": "soffice",                 "Darwin": "LibreOffice",          "Linux": "libreoffice"},
    "notepad":            {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "textedit":           {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "explorer":           {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "file explorer":      {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "finder":             {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "task manager":       {"Windows": "taskmgr.exe",             "Darwin": "Activity Monitor",     "Linux": "gnome-system-monitor"},
    "settings":           {"Windows": "ms-settings:",            "Darwin": "System Preferences",   "Linux": "gnome-control-center"},
    "calculator":         {"Windows": "calc.exe",                "Darwin": "Calculator",           "Linux": "gnome-calculator"},
    "paint":              {"Windows": "mspaint.exe",             "Darwin": "Preview",              "Linux": "gimp"},
    "instagram":          {"Windows": "Instagram",               "Darwin": "Instagram",            "Linux": "firefox"},
    "tiktok":             {"Windows": "TikTok",                  "Darwin": "TikTok",               "Linux": "firefox"},
    "notion":             {"Windows": "Notion",                  "Darwin": "Notion",               "Linux": "notion"},
    "obsidian":           {"Windows": "Obsidian",                "Darwin": "Obsidian",             "Linux": "obsidian"},
    "capcut":             {"Windows": "CapCut",                  "Darwin": "CapCut",               "Linux": "capcut"},
    "steam":              {"Windows": "steam",                   "Darwin": "Steam",                "Linux": "steam"},
    "epic":               {"Windows": "EpicGamesLauncher",       "Darwin": "Epic Games Launcher",  "Linux": "legendary"},
    "epic games":         {"Windows": "EpicGamesLauncher",       "Darwin": "Epic Games Launcher",  "Linux": "legendary"},
    "internet explorer":  {"Windows": "iexplore.exe",            "Darwin": "Safari",               "Linux": "firefox"},
    "ie":                 {"Windows": "iexplore.exe",            "Darwin": "Safari",               "Linux": "firefox"},
    "iexplore":           {"Windows": "iexplore.exe",            "Darwin": "Safari",               "Linux": "firefox"},
    "cursor":             {"Windows": "cursor",                  "Darwin": "Cursor",               "Linux": "cursor"},
}


def resolve_app_command(app_name: str, system: str = _SYSTEM) -> dict:
    key = app_name.lower().strip()

    # Special Case: Internet Explorer on Windows
    if system == "Windows" and key in ["internet explorer", "ie", "iexplore"]:
        # We need to be careful not to resolve to explorer.exe
        ie_exe = "iexplore.exe"
        found = shutil.which(ie_exe)
        if not found:
            # Check common paths
            for p in [
                os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Internet Explorer", ie_exe),
                os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Internet Explorer", ie_exe),
            ]:
                if os.path.exists(p):
                    found = p
                    break

        if found:
            return {"status": "ok", "command": ie_exe, "label": "Internet Explorer"}
        else:
            return {
                "status": "error",
                "message": "Internet Explorer was not found. Use Microsoft Edge or Edge IE mode."
            }

    # 1. Exact alias match
    if key in _APP_ALIASES:
        cmd = _APP_ALIASES[key].get(system, app_name)
        return {"status": "ok", "command": cmd, "label": key}

    # 2. Prevent "Internet Explorer" matching "explorer" alias
    if "internet explorer" in key or "ie" == key:
        # If we reached here, it wasn't caught by exact match or the special case failed
        # We MUST NOT fall back to fuzzy matching "explorer"
        return {
            "status": "error",
            "message": f"Could not resolve '{app_name}' to a valid executable."
        }

    # 3. Fuzzy match (only for non-ambiguous cases)
    dangerous_fuzzy = ["explorer", "code", "cursor"]
    for alias_key, os_map in _APP_ALIASES.items():
        if alias_key in dangerous_fuzzy:
            continue
        if alias_key in key or key in alias_key:
            return {"status": "ok", "command": os_map.get(system, app_name), "label": alias_key}

    return {"status": "ok", "command": app_name, "label": app_name}


def _normalize(raw: str) -> str:
    res = resolve_app_command(raw)
    if res["status"] == "ok":
        return res["command"]
    return raw # Fallback for now, but open_app should handle the error

def _launch_windows(app_name: str) -> bool:

    if shutil.which(app_name) or shutil.which(app_name.split(".")[0]):
        try:
            subprocess.Popen(
                app_name,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1.5)
            return True
        except Exception as e:
            print(f"[open_app] subprocess failed: {e}")

    if ":" in app_name:
        try:
            subprocess.Popen(f"start {app_name}", shell=True)
            time.sleep(1.0)
            return True
        except Exception:
            pass

    return False


def _launch_macos(app_name: str) -> bool:

    try:
        result = subprocess.run(
            ["open", "-a", app_name],
            capture_output=True, timeout=8
        )
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["open", "-a", f"{app_name}.app"],
            capture_output=True, timeout=8
        )
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    binary = shutil.which(app_name) or shutil.which(app_name.lower())
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.0)
            return True
        except Exception:
            pass

    return False


def _launch_linux(app_name: str) -> bool:

    binary = (
        shutil.which(app_name) or
        shutil.which(app_name.lower()) or
        shutil.which(app_name.lower().replace(" ", "-")) or
        shutil.which(app_name.lower().replace(" ", "_"))
    )
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        subprocess.run(
            ["xdg-open", app_name],
            capture_output=True, timeout=5
        )
        return True
    except Exception:
        pass

    for desktop_name in [
        app_name.lower(),
        app_name.lower().replace(" ", "-"),
        app_name.lower().replace(" ", ""),
    ]:
        try:
            result = subprocess.run(
                ["gtk-launch", desktop_name],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass

    return False


_OS_LAUNCHERS = {
    "Windows": _launch_windows,
    "Darwin":  _launch_macos,
    "Linux":   _launch_linux,
}

def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    app_name = (parameters or {}).get("app_name", "").strip()

    if not app_name:
        return "No application name provided."

    launcher = _OS_LAUNCHERS.get(_SYSTEM)
    if launcher is None:
        return f"Unsupported operating system: {_SYSTEM}"

    # Use Trusted App Resolver
    start_time = time.time()
    trusted_res = resolve_trusted_app(app_name)
    duration_ms = (time.time() - start_time) * 1000
    status = trusted_res["status"]

    print(f"[open_app] Resolution for '{app_name}' took {duration_ms:.1f}ms (Status: {status})")

    if status in ["not_found", "stale", "ambiguous", "registry_only"]:
        return format_app_resolution_message(app_name, trusted_res)

    # If we are here, status is running, installed_verified, or shortcut_valid
    candidate = trusted_res["candidate"]
    normalized = candidate.executable_path or candidate.command or candidate.name

    print(f"[open_app] Launching Trusted: '{app_name}' -> '{normalized}' (Status: {status})")

    if player:
        player.write_log(f"[open_app] {app_name}")

    try:
        if launcher(normalized):
            # Best-effort verification
            time.sleep(1.0) # Increased slightly for reliability
            win = get_active_window_info()
            if win.get("status") == "ok":
                observed_title = win.get("title", "")
                observed_proc = win.get("process_name", "")
                observed = f"{observed_title} {observed_proc}".strip()
                check = verify_app_match(app_name, observed)
                if not check["match"]:
                    reason = check.get("reason", "mismatch")
                    print(f"[open_app] Verification failed: {reason}")
                    return f"Opened something, but it might not be {app_name}. (Detected: {observed})"

            return f"Opened {app_name}."

        return (
            f"Could not confirm that {app_name} launched. "
            f"The executable at '{normalized}' may have failed to start."
        )
    except Exception as e:
        print(f"[open_app] Error: {e}")
        return f"Failed to open {app_name}: {e}"
