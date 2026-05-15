import os
import json
import platform
import shutil
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict
import re

_IS_WINDOWS = platform.system() == "Windows"

if _IS_WINDOWS:
    import winreg
    try:
        import psutil
        _HAS_PSUTIL = True
    except ImportError:
        _HAS_PSUTIL = False
else:
    winreg = None
    _HAS_PSUTIL = False

@dataclass
class AppCandidate:
    name: str
    normalized_name: str
    executable_path: Optional[str] = None
    command: Optional[str] = None
    source: str = "unknown"
    status: str = "not_found"
    confidence: float = 0.0
    evidence: str = ""

    def to_dict(self):
        return asdict(self)

def normalize_app_query(query: str) -> str:
    """Normalizes app query for consistent matching."""
    q = query.lower().strip()
    # Remove common extensions if present
    if q.endswith(".exe"):
        q = q[:-4]
    
    # Specific mappings to canonical names
    mapping = {
        "vscode": "visual studio code",
        "vs code": "visual studio code",
        "code": "visual studio code",
        "cursor": "cursor",
        "codex": "codex",
        "chrome": "google chrome",
        "edge": "microsoft edge",
        "ie": "internet explorer",
        "iexplore": "internet explorer",
        "explorer": "windows file explorer",
        "file explorer": "windows file explorer",
    }
    return mapping.get(q, q)

def classify_candidate(candidate: AppCandidate) -> str:
    """Determines the status of a candidate based on its properties."""
    if not candidate.executable_path:
        if candidate.source == "registry":
            return "registry_only"
        return "not_found"
    
    path = Path(candidate.executable_path)
    if not path.exists():
        return "stale"
    
    # Check if it's currently running (if psutil available)
    if _HAS_PSUTIL:
        try:
            exe_name = path.name.lower()
            for proc in psutil.process_iter(['name', 'exe']):
                try:
                    if proc.info['name'].lower() == exe_name or (proc.info['exe'] and Path(proc.info['exe']).resolve() == path.resolve()):
                        return "running"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

    if candidate.source == "shortcut":
        return "shortcut_valid"
    
    return "installed_verified"

def is_stale_candidate(candidate: AppCandidate) -> bool:
    """Checks if a candidate is no longer valid."""
    if not candidate.executable_path:
        return True
    return not os.path.exists(candidate.executable_path)

class AppInventory:
    def __init__(self):
        self.candidates: List[AppCandidate] = []

    def _add_candidate(self, name: str, exe_path: Optional[str], source: str, evidence: str, confidence: float = 0.8):
        norm = normalize_app_query(name)
        
        # Guard against forbidden overlaps
        if norm == "cursor" and exe_path and "code.exe" in exe_path.lower():
            return
        if norm == "visual studio code" and exe_path and "cursor.exe" in exe_path.lower():
            return
        if norm == "visual studio code" and exe_path and "codex" in exe_path.lower():
            return
        if norm == "internet explorer" and exe_path and "explorer.exe" in exe_path.lower() and "internet explorer" not in exe_path.lower():
            return

        candidate = AppCandidate(
            name=name,
            normalized_name=norm,
            executable_path=exe_path,
            command=exe_path,
            source=source,
            evidence=evidence,
            confidence=confidence
        )
        candidate.status = classify_candidate(candidate)
        self.candidates.append(candidate)

    def scan_path(self):
        """Scans directories in the system PATH."""
        path_env = os.environ.get("PATH", "")
        for part in path_env.split(os.pathsep):
            if not part: continue
            try:
                p = Path(part)
                if not p.exists() or not p.is_dir(): continue
                for item in p.iterdir():
                    if item.is_file() and item.suffix.lower() == ".exe":
                        self._add_candidate(item.stem, str(item), "path", f"Found in PATH: {part}", 0.7)
            except Exception:
                continue

    def scan_registry(self):
        """Scans Windows Registry for installed applications."""
        if not _IS_WINDOWS: return
        
        paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")
        ]
        
        for root, subkey in paths:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, name) as app_key:
                                try:
                                    display_name, _ = winreg.QueryValueEx(app_key, "DisplayName")
                                    try:
                                        install_location, _ = winreg.QueryValueEx(app_key, "InstallLocation")
                                    except FileNotFoundError:
                                        install_location = ""
                                    
                                    # Try to find an executable in install location
                                    exe_path = None
                                    if install_location and os.path.isdir(install_location):
                                        for root_dir, _, files in os.walk(install_location):
                                            for f in files:
                                                if f.lower().endswith(".exe"):
                                                    # Heuristic: pick exe that matches name or common patterns
                                                    if display_name.lower() in f.lower() or "main" in f.lower() or "bin" in root_dir.lower():
                                                        exe_path = os.path.join(root_dir, f)
                                                        break
                                            if exe_path: break
                                    
                                    self._add_candidate(display_name, exe_path, "registry", f"Registry: {subkey}\\{name}", 0.9)
                                except (FileNotFoundError, OSError):
                                    continue
                        except OSError:
                            continue
            except OSError:
                continue

    def scan_start_menu(self):
        """Scans Start Menu shortcuts."""
        if not _IS_WINDOWS: return
        
        roots = [
            Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "Microsoft\\Windows\\Start Menu\\Programs",
            Path(os.environ.get("AppData", "")) / "Microsoft\\Windows\\Start Menu\\Programs"
        ]
        
        for root in roots:
            if not root.exists(): continue
            for item in root.rglob("*.lnk"):
                # We don't resolve the shortcut here to avoid heavy dependencies 
                # unless we find a light way. For now, we treat the shortcut name as a candidate.
                # In a real impl, we'd use Shell32 or similar.
                self._add_candidate(item.stem, None, "shortcut", f"Start Menu: {item}", 0.8)

    def scan_program_files(self):
        """Scans Program Files directories."""
        roots = [
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")),
            Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")),
            Path(os.environ.get("LocalAppData", "")) / "Programs"
        ]
        
        for root in roots:
            if not root.exists(): continue
            try:
                for item in root.iterdir():
                    if item.is_dir():
                        # Look for common exe patterns inside
                        for subitem in item.glob("*.exe"):
                            self._add_candidate(item.name, str(subitem), "program_files", f"Program Files: {root}", 0.7)
            except Exception:
                continue

    def scan_running_processes(self):
        """Scans currently running processes."""
        if not _HAS_PSUTIL: return
        try:
            for proc in psutil.process_iter(['name', 'exe']):
                try:
                    name = proc.info['name']
                    exe = proc.info['exe']
                    if name and exe:
                        self._add_candidate(name.replace(".exe", ""), exe, "running", "Process list", 1.0)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

    def build(self, light_scan=True):
        """Builds the full inventory."""
        self.candidates = []
        self.scan_running_processes()
        self.scan_path()
        if not light_scan:
            self.scan_program_files()
            self.scan_registry()
            self.scan_start_menu()
        return self

def build_app_inventory(light_scan=True) -> AppInventory:
    return AppInventory().build(light_scan=light_scan)

def find_app_candidates(query: str, inventory: Optional[AppInventory] = None) -> List[AppCandidate]:
    if inventory is None:
        inventory = build_app_inventory(light_scan=False)
    
    norm_query = normalize_app_query(query)
    matches = []
    
    for c in inventory.candidates:
        if c.normalized_name == norm_query:
            matches.append(c)
        elif norm_query in c.normalized_name or c.normalized_name in norm_query:
            # Fuzzy match
            matches.append(c)
            
    return matches

def resolve_trusted_app(query: str, inventory: Optional[AppInventory] = None) -> Dict:
    candidates = find_app_candidates(query, inventory)
    norm_query = normalize_app_query(query)
    
    if not candidates:
        return {"status": "not_found", "query": query, "candidate": None}
    
    # Filter out forbidden overlaps explicitly again
    trusted = []
    for c in candidates:
        if norm_query == "visual studio code" and "cursor" in c.normalized_name: continue
        if norm_query == "cursor" and "visual studio code" in c.normalized_name: continue
        if norm_query == "visual studio code" and "codex" in c.normalized_name: continue
        if norm_query == "internet explorer" and "explorer" in c.normalized_name and "internet" not in c.normalized_name: continue
        
        if c.status != "stale":
            trusted.append(c)
            
    if not trusted:
        # All candidates are stale
        return {"status": "stale", "query": query, "candidate": candidates[0]}
    
    # Sort by confidence and status priority
    status_priority = {
        "running": 0,
        "installed_verified": 1,
        "shortcut_valid": 2,
        "registry_only": 3,
        "stale": 4
    }
    
    trusted.sort(key=lambda x: (status_priority.get(x.status, 99), -x.confidence))
    
    # Check for ambiguity
    best = trusted[0]
    others = [t for t in trusted[1:] if t.normalized_name != best.normalized_name]
    
    if others:
        # If we have multiple different normalized names that are equally strong
        if status_priority.get(best.status) == status_priority.get(others[0].status):
            return {"status": "ambiguous", "query": query, "candidates": trusted}

    return {"status": best.status, "query": query, "candidate": best}

def save_inventory_cache(inventory: AppInventory, path: str):
    data = [c.to_dict() for c in inventory.candidates]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_inventory_cache(path: str) -> AppInventory:
    inventory = AppInventory()
    if not os.path.exists(path):
        return inventory
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        for item in data:
            c = AppCandidate(**item)
            inventory.candidates.append(c)
    return inventory
