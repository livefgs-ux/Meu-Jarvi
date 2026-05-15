import os
import json
import platform
import shutil
import time
import threading
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict
import re

_IS_WINDOWS = platform.system() == "Windows"
APP_INVENTORY_CACHE_TTL_SECONDS = 86400  # 24 hours
DEFAULT_CACHE_PATH = ".local_state/app_inventory.json"

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
    candidate_kind: str = "unknown"
    rank_score: int = 0
    rank_reason: str = ""
    is_primary_app_candidate: bool = False

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

def classify_candidate_kind(candidate: AppCandidate) -> str:
    """Classifies the kind of app candidate based on name and path."""
    name = (candidate.name or "").lower()
    path = (candidate.executable_path or "").lower()
    
    if "uninstall" in name or "uninstall" in path: return "uninstaller"
    if any(k in name or k in path for k in ["installer", "setup", "install"]): return "installer"
    if "tunnel" in name or "tunnel" in path: return "tunnel"
    if "service" in name or "service" in path: return "service"
    if any(k in name or k in path for k in ["updater", "update"]): return "helper_binary"
    if any(k in name or k in path for k in ["helper", "crashpad", "telemetry"]): return "helper_binary"
    if "launcher" in name or "launcher" in path: return "launcher"
    
    if "powershell" in name:
        if "ise" in name or "developer" in name:
            return "developer_shell"
            
    if candidate.source == "shortcut":
        return "gui_app"
    
    if candidate.source == "registry" and candidate.executable_path:
        return "gui_app"
        
    if "system32" in path or "syswow64" in path:
        return "system_tool"
        
    if candidate.source == "path":
        return "cli_tool"
        
    return "unknown"

def rank_candidate(candidate: AppCandidate, query: str):
    """Calculates rank score and reason for a candidate."""
    score = 0
    reasons = []
    kind = classify_candidate_kind(candidate)
    candidate.candidate_kind = kind
    
    q_norm = query.lower()
    name_low = candidate.name.lower()
    
    # Kind-based base score
    kind_scores = {
        "gui_app": 100,
        "launcher": 90,
        "developer_shell": 50,
        "system_tool": 40,
        "cli_tool": 30,
        "unknown": 10,
        "tunnel": -50,
        "service": -50,
        "helper_binary": -60,
        "installer": -100,
        "uninstaller": -100
    }
    score += kind_scores.get(kind, 0)
    reasons.append(f"kind:{kind}({kind_scores.get(kind, 0)})")
    
    # Source boost
    if candidate.source == "shortcut":
        score += 20
        reasons.append("source:shortcut(+20)")
    elif candidate.source == "registry":
        score += 10
        reasons.append("source:registry(+10)")
        
    # Name match boost
    if name_low == q_norm:
        score += 50
        reasons.append("exact_name_match(+50)")
    elif q_norm in name_low:
        score += 10
        reasons.append("partial_name_match(+10)")
        
    # Path heuristics
    path = (candidate.executable_path or "").lower()
    if path:
        # Avoid common sub-folders for primary apps
        if any(x in path for x in ["\\bin\\", "\\tools\\", "\\resources\\", "\\app\\"]):
            score -= 10
            reasons.append("path:subfolder(-10)")
        if "cursor-tunnel" in path or "cursor-tunnel" in name_low:
            score -= 40
            reasons.append("path:tunnel_keyword(-40)")
            
    # Keywords penalties
    if any(k in name_low or k in path for k in ["updater", "update"]):
        score -= 20
        reasons.append("name:updater_keyword(-20)")
    if any(k in name_low or k in path for k in ["helper", "crashpad", "telemetry"]):
        score -= 10
        reasons.append("name:helper_keyword(-10)")

    # PowerShell specific rules
    if "powershell" in q_norm:
        if "ise" in name_low and "ise" not in q_norm:
            score -= 80
            reasons.append("powershell:ise_not_requested(-80)")
        if "developer" in name_low and "developer" not in q_norm:
            score -= 80
            reasons.append("powershell:developer_not_requested(-80)")

    candidate.rank_score = score
    candidate.rank_reason = "; ".join(reasons)
    candidate.is_primary_app_candidate = (score >= 80)

class AppInventory:
    def __init__(self):
        self.candidates: List[AppCandidate] = []

    def _add_candidate(self, name: str, exe_path: Optional[str], source: str, evidence: str, confidence: float = 0.8, query_context: Optional[str] = None):
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
        
        # Rank it using name as a proxy for the query if context not provided
        rank_candidate(candidate, query_context or name)
        
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
        if c.normalized_name == norm_query or norm_query in c.normalized_name or c.normalized_name in norm_query:
            # Re-rank based on ACTUAL query
            rank_candidate(c, query)
            matches.append(c)

    return matches

def resolve_trusted_app(
    query: str,
    inventory: Optional[AppInventory] = None,
    force_refresh: bool = False,
    include_alternatives: bool = False,
) -> Dict:
    if inventory is None:
        inventory = get_cached_or_build_inventory(light_scan=True, force_refresh=force_refresh)

    candidates = find_app_candidates(query, inventory)
    norm_query = normalize_app_query(query)

    if not candidates:
        result = {
            "status": "not_found",
            "query": query,
            "candidate": None,
        }
        if include_alternatives:
            result["alternatives"] = find_alternative_apps(query, inventory)
        return result

    # Filter out forbidden overlaps explicitly again
    trusted = []
    for c in candidates:
        if norm_query == "visual studio code" and "cursor" in c.normalized_name: continue
        if norm_query == "cursor" and "visual studio code" in c.normalized_name: continue
        if norm_query == "visual studio code" and "codex" in c.normalized_name: continue
        if norm_query == "internet explorer" and "explorer" in c.normalized_name and "internet" not in c.normalized_name: continue

        # Never auto-select installer/uninstaller unless specifically requested
        if c.candidate_kind in ["installer", "uninstaller"]:
            kind_keywords = ["install", "setup", "uninstall"]
            if not any(k in query.lower() for k in kind_keywords):
                continue

        if c.status != "stale":
            trusted.append(c)

    if not trusted:
        # All candidates are stale or filtered by policy
        # If we had at least one candidate that wasn't stale, but it was filtered, return not_found
        for c in candidates:
            if c.status != "stale" and c not in trusted:
                return {"status": "not_found", "query": query, "candidate": None}
        
        if candidates:
            return {"status": "stale", "query": query, "candidate": candidates[0]}
        return {"status": "not_found", "query": query, "candidate": None}

    # Sort by Rank Score (Primary), then status priority, then confidence
    status_priority = {
        "running": 0,
        "installed_verified": 1,
        "shortcut_valid": 2,
        "registry_only": 3,
        "stale": 4
    }

    # Ranking is the main decision factor now
    trusted.sort(key=lambda x: (-x.rank_score, status_priority.get(x.status, 99), -x.confidence))

    best = trusted[0]
    
    # If the best candidate is significantly better than others, no ambiguity
    # Use human-readable name for ambiguity check if scores are close
    others = [t for t in trusted[1:] if t.name.lower() != best.name.lower()]
    
    if others:
        best_score = best.rank_score
        second_best_score = others[0].rank_score
        
        # If score difference is small (< 15) and both are strong, it's ambiguous
        if abs(best_score - second_best_score) < 15:
            return {"status": "ambiguous", "query": query, "candidates": trusted}

    return {"status": best.status, "query": query, "candidate": best}

def find_alternative_apps(query: str, inventory: AppInventory) -> List[str]:
    norm = normalize_app_query(query)
    alts = []

    related = {
        "visual studio code": ["cursor", "codex"],
        "google chrome": ["microsoft edge"],
        "internet explorer": ["microsoft edge"]
    }

    targets = related.get(norm, [])
    for target_norm in targets:
        # Check if target exists in inventory
        for c in inventory.candidates:
            if c.normalized_name == target_norm and c.status != "stale":
                alts.append(c.name)
                break

    return list(set(alts))

def _refresh_inventory_cache(cache_path: str, light_scan: bool):
    try:
        inventory = build_app_inventory(light_scan=light_scan)
        save_inventory_cache(inventory, cache_path)
    except Exception:
        pass


def _schedule_inventory_refresh(cache_path: str, light_scan: bool = True):
    worker = threading.Thread(
        target=_refresh_inventory_cache,
        args=(cache_path, light_scan),
        daemon=True,
    )
    worker.start()
    return worker


def get_cached_or_build_inventory(light_scan=True, force_refresh=False, cache_path=None) -> AppInventory:
    if cache_path is None:
        cache_path = DEFAULT_CACHE_PATH

    if os.path.exists(cache_path):
        try:
            inventory, timestamp = load_inventory_cache(cache_path)
            if not force_refresh and time.time() - timestamp < APP_INVENTORY_CACHE_TTL_SECONDS:
                return inventory
            if not force_refresh:
                setattr(inventory, "needs_refresh", True)
                _schedule_inventory_refresh(cache_path, light_scan=light_scan)
                return inventory
        except Exception:
            pass

    # Rebuild only when explicitly requested or when cache is missing/corrupt.
    inventory = build_app_inventory(light_scan=light_scan)
    save_inventory_cache(inventory, cache_path)
    return inventory

def format_app_resolution_message(query: str, resolution: Dict) -> str:
    status = resolution.get("status")
    name = resolution.get("candidate").name if resolution.get("candidate") else query
    allow_alternatives = bool(resolution.get("show_alternatives") or resolution.get("include_alternatives"))

    if status == "not_found":
        if allow_alternatives:
            alternatives = resolution.get("alternatives", [])
            if alternatives:
                return (
                    f"{query} não parece estar instalado neste PC. "
                    f"Posso te ajudar a instalar? Se você quiser uma alternativa, encontrei: {', '.join(alternatives)}."
                )
        return f"{query} não parece estar instalado neste PC. Posso te ajudar a instalar?"

    if status == "stale":
        return (
            f"Encontrei sinais antigos de {name}, mas o executável não existe mais. "
            f"Parece desinstalado ou quebrado. Posso te ajudar a reinstalar?"
        )

    if status == "ambiguous":
        candidates = resolution.get("candidates", [])
        names = ", ".join([c.name for c in candidates[:3]])
        return f"Encontrei mais de uma instalação possível de {name}: {names}. Qual delas você quer abrir?"

    if status == "registry_only":
        return f"Encontrei uma entrada de {name}, mas não consegui confirmar o executável. Posso verificar a instalação?"

    return f"Resultado inesperado para {query} (Status: {status})."

def save_inventory_cache(inventory: AppInventory, path: str):
    data = {
        "timestamp": time.time(),
        "candidates": [c.to_dict() for c in inventory.candidates]
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_inventory_cache(path: str) -> tuple:
    inventory = AppInventory()
    if not os.path.exists(path):
        return inventory, 0

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, dict) and "candidates" in data:
            timestamp = data.get("timestamp", 0)
            for item in data["candidates"]:
                c = AppCandidate(**item)
                inventory.candidates.append(c)
            return inventory, timestamp
        else:
            # Legacy format
            for item in data:
                c = AppCandidate(**item)
                inventory.candidates.append(c)
            return inventory, 0
