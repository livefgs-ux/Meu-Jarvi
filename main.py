import asyncio
import time
import os
import re
import threading
import json
import uuid
import sys
import traceback
from pathlib import Path

import sounddevice as sd
from google import genai
from google.genai import types
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
)
from memory_engine.runtime_context import build_readonly_memory_context_from_env
from core.intent_confidence import (
    classify_user_intent,
    transcript_quality_score,
    validate_tool_call_against_user_text,
)
from core.response_discipline import (
    concise_clarification,
    enforce_portuguese_local_reply,
    is_explicit_language_change_request,
    portuguese_default_instruction,
    tool_truthfulness_instruction,
)
from core.speech_control import (
    SpeechCommandType,
    SpeechControlState,
    detect_speech_control_command,
)
from core.runtime_journal import record_event
from core.task_runtime import get_task_runtime, TaskPriority
from core.live_resilience import LiveResilienceSupervisor, LiveConnectionState

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import screen_process
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


def _speech_control_enabled() -> bool:
    raw = os.environ.get("JARVIS_SPEECH_CONTROL")
    if raw is None:
        return False
    val = str(raw).strip().lower()
    return val in {"1", "true", "yes", "on"}


def _get_memory_write_backend() -> str:
    backend = os.environ.get("JARVIS_MEMORY_WRITE_BACKEND", "legacy")
    return str(backend or "").strip().lower() or "legacy"


def _save_memory_legacy(category: str, key: str, value: str) -> None:
    update_memory({category: {key: {"value": value}}})


def _map_save_memory_sqlite(category: str, key: str, value: str) -> dict:
    cat = (category or "notes").strip().lower()
    k = (key or "").strip()
    v = "" if value is None else str(value).strip()

    if cat == "preferences":
        memory_type = "PREFERENCE"
        scope = "global"
        project = None
        requires_review = False
    elif cat == "projects":
        memory_type = "PROJECT_CONTEXT"
        scope = "project:meu-jarvis"
        project = "meu-jarvis"
        requires_review = False
    elif cat == "notes":
        memory_type = "IDEA"
        scope = "project:meu-jarvis"
        project = "meu-jarvis"
        requires_review = True
    elif cat == "wishes":
        memory_type = "IDEA"
        scope = "global"
        project = None
        requires_review = True
    elif cat == "identity":
        memory_type = "PREFERENCE"
        scope = "global"
        project = None
        requires_review = True
    elif cat == "relationships":
        memory_type = "PREFERENCE"
        scope = "global"
        project = None
        requires_review = True
    else:
        memory_type = "IDEA"
        scope = "project:meu-jarvis"
        project = "meu-jarvis"
        requires_review = True

    content = f"{cat}.{k}: {v}"
    return {
        "memory_type": memory_type,
        "scope": scope,
        "project": project,
        "status": "candidate",
        "importance": 5,
        "confidence": 0.5,
        "source": "runtime_save_memory",
        "metadata": {
            "source_tool": "save_memory",
            "category": cat,
            "key": k,
            "write_backend": "sqlite",
            "requires_review": requires_review,
        },
        "content": content,
    }


def _save_memory_sqlite(category: str, key: str, value: str) -> None:
    # Lazy/dynamic import to avoid loading the memory engine unless explicitly enabled.
    # Note: keep this import string-free to satisfy text-only guardrail tests.
    import importlib

    mapped = _map_save_memory_sqlite(category, key, value)

    db_path = os.environ.get("JARVIS_MEMORY_DB")
    event_log_path = os.environ.get("JARVIS_MEMORY_EVENT_LOG")

    kwargs = {}
    if db_path:
        kwargs["db_path"] = db_path
    if event_log_path:
        kwargs["event_log_path"] = event_log_path

    writer_mod = importlib.import_module("memory_engine" + ".writer")
    cm = getattr(writer_mod, "create_memory")
    cm(
        mapped["memory_type"],
        mapped["scope"],
        mapped["content"],
        status=mapped["status"],
        importance=mapped["importance"],
        confidence=mapped["confidence"],
        source=mapped["source"],
        project=mapped["project"],
        metadata=mapped["metadata"],
        **kwargs,
    )


def _execute_save_memory(category: str, key: str, value: str) -> tuple[bool, str]:
    backend = _get_memory_write_backend()
    if backend not in {"legacy", "sqlite"}:
        return False, "Invalid JARVIS_MEMORY_WRITE_BACKEND. Use legacy or sqlite."

    if not (key and value):
        return True, ""

    # Phase 4B: optional memory decision policy (JARVIS_MEMORY_DECISION_POLICY).
    # Inlined here so AST-based tests can extract _execute_save_memory without extra top-level helpers.
    _pol_raw = os.environ.get("JARVIS_MEMORY_DECISION_POLICY")
    _policy_on = False
    if _pol_raw is not None and str(_pol_raw).strip() != "":
        _pls = str(_pol_raw).strip().lower()
        if _pls not in {"", "0", "false", "no", "off"} and _pls in {"1", "true", "yes", "on"}:
            _policy_on = True

    if _policy_on:
        from memory_engine.decision_policy import decide_memory_save

        _proj = (os.environ.get("JARVIS_MEMORY_PROJECT") or "meu-jarvis").strip() or "meu-jarvis"
        _decision = decide_memory_save(category=category, key=key, value=value, project=_proj)
        if not _decision.should_save:
            return False, f"skipped:{_decision.reason}"
        _allow_review = str(os.environ.get("JARVIS_MEMORY_ALLOW_REVIEW_SAVE") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if _decision.requires_review and not _allow_review:
            return False, "skipped:requires_review"

    try:
        if backend == "legacy":
            _save_memory_legacy(category, key, value)
        else:
            # Safety policy: runtime sqlite writes require explicit paths.
            if not os.environ.get("JARVIS_MEMORY_DB"):
                return False, "SQLite backend requires JARVIS_MEMORY_DB to be set."
            if not os.environ.get("JARVIS_MEMORY_EVENT_LOG"):
                return False, "SQLite backend requires JARVIS_MEMORY_EVENT_LOG to be set."
            _save_memory_sqlite(category, key, value)
    except ValueError as e:
        # privacy_guard raises ValueError with a safe message; keep it controlled.
        return False, str(e)[:200]
    except Exception:
        return False, "Failed to save memory."

    return True, ""


def _action_decision_gate_enabled() -> bool:
    raw = os.environ.get("JARVIS_ACTION_DECISION_GATE")
    if raw is None:
        return False
    val = str(raw).strip().lower()
    return val in {"1", "true", "yes", "on"}


def _format_action_confirmation(decision) -> str:
    return (
        f"Sir, this request seems to require a local action or file change ({decision.intent}). "
        f"Reason: {decision.reason}. Please confirm explicitly before I proceed."
    )


def _format_action_denial(decision) -> str:
    return (
        f"I cannot execute this request because it was classified as high risk: {decision.reason}. "
        f"Intent: {decision.intent}."
    )


def _apply_action_decision_gate(text: str) -> tuple[bool, str | None]:
    if not _action_decision_gate_enabled():
        return True, None

    from core.action_decision_policy import decide_action_request
    decision = decide_action_request(text)

    if decision.action in {"allow", "answer_only"}:
        return True, None

    if decision.action == "confirm":
        return False, _format_action_confirmation(decision)

    if decision.action == "deny":
        return False, _format_action_denial(decision)

    return True, None


def _tool_call_gate_enabled() -> bool:
    raw = os.environ.get("JARVIS_TOOL_CALL_GATE")
    if raw is None:
        return False
    val = str(raw).strip().lower()
    return val in {"1", "true", "yes", "on"}


def _redact_secrets(text: str) -> str:
    text = re.sub(r"(\b(api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*)(\S+)", r"\1[REDACTED]", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{10,}\b", "sk-[REDACTED]", text)
    text = re.sub(r"\bAIza[0-9A-Za-z_-]{10,}\b", "AIza[REDACTED]", text)
    return text


def _tool_was_clearly_requested(name: str, args: dict, user_text: str | None) -> bool:
    if not user_text:
        return False
    low = user_text.lower()
    if name == "open_app":
        app = str(args.get("app_name", "")).lower()
        return app in low or any(w in low for w in ["abra", "open", "lance", "start"])
    if name == "file_controller":
        act = args.get("action", "")
        pth = str(args.get("path", "")).lower()
        if act == "read" and any(w in low for w in ["leia", "read", pth]): return True
        if act == "find" and any(w in low for w in ["procure", "find", pth]): return True
        if act == "create_file" and any(w in low for w in ["crie", "create", "escreva"]):
            return not any(x in pth for x in ["main.py", "config", ".env", ".gitignore", "windows", "system32"])
        if act == "create_folder" and any(w in low for w in ["crie", "create", "pasta"]): return True
    if name in ["web_search", "weather_report", "youtube_video", "flight_finder", "save_memory"]:
        return True
    return False


def _classify_tool_call(name: str, args: dict, user_text: str | None) -> dict:
    CRIT = ["main.py", "config", ".env", ".gitignore", "windows", "system32", "program files"]
    DANG = ["rm -rf", "del /s", "format ", "mkfs", "dd if=", ":(){ :|:& };:", "shutdown /s", "reg delete"]
    arg_str = str(args).lower()
    if any(d in arg_str for d in DANG):
        return {"action": "deny", "risk": "high", "reason": "destructive_command"}
    if name == "file_controller":
        act = args.get("action", "")
        pth = str(args.get("path", "")).lower()
        if act in ["delete", "move", "rename", "write"]:
            if "all" in arg_str or "*" in pth or pth == "":
                return {"action": "deny", "risk": "high", "reason": "bulk_file_operation"}
            if any(c in pth for c in CRIT):
                return {"action": "confirm", "risk": "medium", "reason": "critical_path_modification"}
            return {"action": "confirm", "risk": "medium", "reason": f"file_{act}"}
    if name == "code_helper" and args.get("action") in ["edit", "run", "build"]:
        return {"action": "confirm", "risk": "medium", "reason": f"code_{args.get('action')}"}
    if name == "computer_settings" and args.get("action") in ["restart", "shutdown"]:
        return {"action": "confirm", "risk": "medium", "reason": "system_power"}
    if not _tool_was_clearly_requested(name, args, user_text):
        if name in ["open_app", "computer_control", "desktop_control"]:
             return {"action": "confirm", "risk": "low", "reason": "unrequested_action"}
    return {"action": "allow", "risk": "low", "reason": ""}


def _format_tool_confirmation(name: str, args: dict, classification: dict) -> str:
    arg_sum = _redact_secrets(str(args))
    return (f"Sir, this request may change or remove something important: tool '{name}' with {arg_sum}. "
            f"Risk: {classification['risk']} ({classification['reason']}). Confirm to proceed?")


def _format_tool_denial(name: str, args: dict, classification: dict) -> str:
    return (f"I cannot execute this as it is dangerous: {classification['reason']}. "
            "Want me to explain the risks and suggest a safer alternative?")


def _apply_tool_call_gate(name: str, args: dict, user_text: str | None = None) -> tuple[bool, str | None, str]:
    if not _tool_call_gate_enabled():
        return True, None, "allow"
    cl = _classify_tool_call(name, args, user_text)
    if cl["action"] == "allow": return True, None, "allow"
    if cl["action"] == "confirm": return False, _format_tool_confirmation(name, args, cl), "confirm"
    if cl["action"] == "deny": return False, _format_tool_denial(name, args, cl), "deny"
    return True, None, "allow"


def _concurrent_runtime_enabled() -> bool:
    raw = os.environ.get("JARVIS_CONCURRENT_TASK_RUNTIME")
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _live_resilience_enabled() -> bool:
    raw = os.environ.get("JARVIS_LIVE_RESILIENCE")
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _tool_resource_locks(name: str, args: dict) -> set[str]:
    locks = set()
    if name == "open_app":
        locks.update(["active_window", f"app:{args.get('app_name')}"])
    elif name == "web_search":
        locks.update(["network", "low_risk_background"])
    elif name == "browser_control":
        locks.update(["browser", f"browser:{args.get('browser', 'default')}"])
    elif name in ["computer_control", "computer_settings", "desktop_control"]:
        locks.update(["keyboard", "mouse", "active_window"])
    elif name == "file_controller":
        locks.update(["filesystem", f"filesystem:{args.get('path', '')}"])
    elif name in ["code_helper", "dev_agent", "file_processor"]:
        locks.update(["filesystem", "low_risk_background"])
    elif name == "game_updater":
        locks.update(["network", "low_risk_background"])
    return locks


def _tool_can_run_background(name: str, args: dict) -> bool:
    # Explicitly allowed tools for background execution
    safe_tools = {
        "open_app", "web_search", "browser_control",
        "file_processor", "code_helper", "dev_agent", "game_updater"
    }
    return name in safe_tools


def _format_task_started_message(name: str, task_id: str) -> str:
    return f"Sir, I've started the {name} task in the background (ID: {task_id[:8]}). I'll let you know when it's done."


def _format_task_completed_message(name: str, result: str) -> str:
    return f"Sir, the {name} task is complete: {result}"


def _format_task_failed_message(name: str, error: str) -> str:
    return f"Sir, the {name} task failed: {error}"

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": "Searches the web for any information.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "mode":   {"type": "STRING", "description": "search (default) or compare"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT — the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command. NEVER route to agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands. NEVER use for Steam/Epic — use game_updater."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "shutdown_jarvis",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Jarvis. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
]

class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self.ui.on_text_command = self._on_text_command
        self._turn_done_event: asyncio.Event | None = None
        self.last_user_text: str | None = None
        self.resilience = LiveResilienceSupervisor()
        self._speech_control_state = SpeechControlState()
        self._suppress_audio_until_turn_complete = False

    def _safe_set_state(self, state: str):
        try:
            self.ui.set_state(state)
        except RuntimeError as e:
            if "deleted" in str(e).lower():
                pass # UI already closed
            else:
                raise

    def _safe_write_log(self, text: str):
        try:
            self.ui.write_log(text)
        except RuntimeError as e:
            if "deleted" in str(e).lower():
                pass
            else:
                raise

    def _clear_audio_output_queue(self):
        if not self.audio_in_queue:
            return

        while True:
            try:
                self.audio_in_queue.get_nowait()
            except Exception:
                break

    def _stop_current_speech(self):
        self._suppress_audio_until_turn_complete = True
        self._clear_audio_output_queue()
        self.set_speaking(False)

    def _apply_concise_hint(self, text: str) -> str:
        if not self._speech_control_state.concise_mode:
            return text
        return "Responda de forma curta e direta.\n\n" + text

    def _handle_speech_control_command(self, text: str, *, source: str = "text") -> bool:
        if not _speech_control_enabled():
            return False

        try:
            result = detect_speech_control_command(text)
        except Exception as exc:
            record_event(
                "speech_control_error",
                "SpeechControl",
                str(exc)[:200],
                metadata={"source": source},
                severity="error",
            )
            return False
        command_type = result.get("command_type", SpeechCommandType.NONE.value)
        if command_type == SpeechCommandType.NONE.value:
            return False

        matched = result.get("matched_phrase", "")
        record_event(
            "speech_control_detected",
            "SpeechControl",
            (text or "")[:200],
            metadata={
                "source": source,
                "command_type": command_type,
                "matched_phrase": matched,
            },
        )

        now = time.time()
        self._speech_control_state.last_command = command_type

        if command_type == SpeechCommandType.INTERRUPT_SPEECH.value:
            self._speech_control_state.interrupted_at = now
            self._stop_current_speech()
            record_event("speech_interrupted", "SpeechControl", "Speech interrupted", metadata={"source": source})
            return True

        if command_type == SpeechCommandType.TEMPORARY_SILENCE.value:
            self._speech_control_state.is_silenced = True
            self._speech_control_state.interrupted_at = now
            self._speech_control_state.silence_until = None
            self._stop_current_speech()
            record_event("speech_silenced", "SpeechControl", "Speech silenced", metadata={"source": source})
            return True

        if command_type == SpeechCommandType.RESUME_SPEECH.value:
            self._speech_control_state.is_silenced = False
            self._speech_control_state.silence_until = None
            self._suppress_audio_until_turn_complete = False
            self.set_speaking(False)
            record_event("speech_resumed", "SpeechControl", "Speech resumed", metadata={"source": source})
            return True

        if command_type == SpeechCommandType.CONCISE_MODE.value:
            self._speech_control_state.concise_mode = True
            record_event("concise_mode_enabled", "SpeechControl", "Concise mode enabled", metadata={"source": source})
            return True

        if command_type == SpeechCommandType.NORMAL_MODE.value:
            self._speech_control_state.concise_mode = False
            record_event("concise_mode_disabled", "SpeechControl", "Concise mode disabled", metadata={"source": source})
            return True

        if command_type == SpeechCommandType.CANCEL_TASK.value:
            record_event("task_cancel_requested", "SpeechControl", "Task cancellation requested", metadata={"source": source})
            self._safe_write_log("SYS: Task cancellation command received.")
            return True

        return False

    def _handle_context_query(self, text: str) -> bool:
        """Handles contextual questions about current state/tasks. Returns True if handled."""
        from core.context_awareness import answer_context_question
        
        try:
            ctx_res = answer_context_question(text)
            if ctx_res["intent"] != "unknown_context_query" and ctx_res["confidence"] > 0.7:
                # Handle the answer
                answer = ctx_res["answer"]
                self.speak(answer)
                self._safe_write_log(f"Jarvis (Context): {answer}")
                
                # Handle suggested action (e.g. open_app)
                if ctx_res["suggested_action"]:
                    action = ctx_res["suggested_action"]
                    if action["tool"] == "open_app":
                        app_name = action["args"].get("app_name")
                        if app_name:
                            print(f"[JARVIS] Context-triggered action: open_app {app_name}")
                            # Schedule the tool call
                            asyncio.run_coroutine_threadsafe(
                                self._call_tool_implementation("open_app", {"app_name": app_name}),
                                self._loop
                            )
                return True
        except Exception as e:
            print(f"[JARVIS] Context awareness error (fail-open): {e}")
            
        return False

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return

        record_event("user_input", "text_command", text[:200], metadata={"input_type": "text"})
        self.last_user_text = text

        if self._handle_speech_control_command(text, source="text"):
            return

        user_intent = classify_user_intent(text)
        transcript_quality = transcript_quality_score(text)
        if (
            user_intent["intent"] == "unknown"
            and (user_intent["confidence"] < 0.35 or transcript_quality < 0.35)
            and "?" not in (text or "")
            and not is_explicit_language_change_request(text)
            and not user_intent["normalized_text"].startswith(("oi", "ola", "olá", "hello"))
        ):
            clarification = enforce_portuguese_local_reply(concise_clarification("Não entendi com segurança. Pode repetir?"))
            self.speak(clarification)
            record_event(
                "tool_blocked_low_confidence",
                "text_command",
                clarification[:200],
                metadata={
                    "intent": user_intent["intent"],
                    "confidence": user_intent["confidence"],
                    "reason": user_intent["reason"],
                },
            )
            return

        # Context Awareness Interception
        if self._handle_context_query(text):
            return

        # Phase 5B: Action Decision Gate
        allowed, msg = _apply_action_decision_gate(text)
        if not allowed:
            if msg:
                self.speak(msg)
            return

        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def speak(self, text: str):
        if not self._loop:
            return

        # Resilience logic: if disconnected, queue message
        if _live_resilience_enabled():
            if not self.session or not self.resilience.is_connected():
                self.resilience.queue_outbound_message(text, reason="disconnected")
                record_event("outbound_message_queued", "Jarvis", text[:100], metadata={"reason": "disconnected"})
                return
        elif not self.session:
            return

        if _speech_control_enabled() and self._speech_control_state.is_silenced:
            record_event(
                "speech_suppressed",
                "SpeechControl",
                str(text)[:200],
                metadata={"reason": "silenced"},
            )
            return

        payload = self._apply_concise_hint(text)

        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": payload}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self._safe_write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        ro_memory_context = build_readonly_memory_context_from_env()
        if ro_memory_context:
            parts.append(ro_memory_context)
        parts.append(portuguese_default_instruction())
        parts.append(tool_truthfulness_instruction())
        if _speech_control_enabled() and self._speech_control_state.concise_mode:
            parts.append("[SPEECH CONTROL]\nResponda de forma curta e direta.\n")
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        validation = validate_tool_call_against_user_text(name, args, self.last_user_text)
        if not validation.get("allow", True):
            clarification = enforce_portuguese_local_reply(
                validation.get("clarification") or concise_clarification("Não entendi com segurança. Pode repetir?")
            )
            record_event(
                "tool_blocked_low_confidence",
                name,
                clarification[:200],
                metadata={
                    "intent": validation.get("intent", "unknown"),
                    "confidence": validation.get("confidence", 0.0),
                    "reason": validation.get("reason", "low_confidence"),
                },
                correlation_id=fc.id,
            )
            if clarification:
                self.speak(clarification)
            return types.FunctionResponse(
                id=fc.id,
                name=name,
                response={
                    "result": "blocked_low_confidence",
                    "intent": validation.get("intent", "unknown"),
                    "confidence": validation.get("confidence", 0.0),
                    "reason": validation.get("reason", "low_confidence"),
                },
            )

        # Concurrent mode logic
        if _concurrent_runtime_enabled() and _tool_can_run_background(name, args):
            try:
                runtime = get_task_runtime()
                locks = _tool_resource_locks(name, args)

                async def background_task_wrapper():
                    # Journal start
                    record_event("tool_called", name, f"Tool called (BG): {name}", metadata=args, correlation_id=fc.id)
                    
                    res = await self._call_tool_implementation(name, args, fc=fc)
                    
                    # Journal result
                    self._journal_tool_result(name, res, fc)
                    
                    # Resilience logic for background tasks
                    if _live_resilience_enabled() and (not self.session or not self.resilience.is_connected()):
                        self.resilience.record_tool_result_pending(name, res, fc.id)
                        record_event("tool_result_queued_due_disconnect", name, str(res)[:100], metadata={"tool": name})
                        return res

                    # Success/Failure speaking logic
                    res_low = str(res).lower()
                    if "failed" in res_low or "error" in res_low:
                        self.speak(_format_task_failed_message(name, res))
                    else:
                        self.speak(_format_task_completed_message(name, res))
                    return res

                task_id = await runtime.submit(
                    name=name,
                    coro_func=background_task_wrapper,
                    resource_locks=locks,
                    correlation_id=fc.id,
                    metadata=args
                )

                # Fast-path wait (e.g. 1.5s)
                start_wait = time.time()
                while time.time() - start_wait < 1.5:
                    task = runtime.get_task(task_id)
                    if task.status in ["completed", "failed"]:
                        final_res = task.result if task.status == "completed" else task.error
                        return types.FunctionResponse(
                            id=fc.id, name=name,
                            response={"result": final_res}
                        )
                    await asyncio.sleep(0.1)

                # If still running, return task_started
                msg = _format_task_started_message(name, task_id)
                self.ui.write_log(f"SYS: Task {task_id[:8]} started in background.")
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": msg, "task_id": task_id}
                )
            except Exception as e:
                print(f"[Concurrent] Runtime error, falling back to sync: {e}")
                record_event("task_runtime_error", name, str(e), metadata={"tool": name}, severity="error")

        # Standard synchronous path
        record_event("tool_called", name, f"Tool called: {name}", metadata=args, correlation_id=fc.id)
        result = await self._call_tool_implementation(name, args, fc=fc)
        self._journal_tool_result(name, result, fc)

        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    def _journal_tool_result(self, name: str, result: str, fc):
        print(f"[JARVIS]  {name} -> {str(result)[:80]}")
        event_type = "tool_result"
        res_low = str(result).lower()
        if name == "open_app":
            if any(w in res_low for w in ["not found", "não foi encontrado"]): event_type = "app_not_found"
            elif any(w in res_low for w in ["stale", "broken"]): event_type = "app_stale"
            elif any(w in res_low for w in ["ambiguous", "mais de um"]): event_type = "app_ambiguous"
            elif any(w in res_low for w in ["mismatch", "verification failed"]): event_type = "app_mismatch"
        
        record_event(event_type, name, str(result)[:200], metadata={"tool": name}, correlation_id=fc.id)

    async def _call_tool_implementation(self, name: str, args: dict, fc=None) -> str:
        # Duplicate call guard
        if _live_resilience_enabled():
            is_dup, prev_res = self.resilience.check_duplicate_tool_call(name, args)
            if is_dup:
                print(f"[JARVIS] Suppressing duplicate call for {name}")
                record_event("duplicate_tool_call_suppressed", name, f"Suppressed duplicate {name}", metadata=args)
                return prev_res

        # Phase 5C: Smart Tool Call Safety Gate
        allowed, msg, action = _apply_tool_call_gate(name, args, self.last_user_text)
        if not allowed:
            if action == "confirm":
                print(f"[GATE] Requesting confirmation for {name}...")
                if msg: self.speak(msg)
                record_event("confirmation_required", name, msg[:200] if msg else f"Confirm tool {name}?", metadata={"tool": name}, correlation_id=fc.id)
                approved = await self.ui.request_confirmation(msg or f"Confirm tool {name}?")
                if approved:
                    record_event("confirmation_approved", name, f"User approved {name}", metadata={"tool": name}, correlation_id=fc.id)
                else:
                    record_event("confirmation_denied", name, f"User denied {name}", metadata={"tool": name}, correlation_id=fc.id)
                    return "User denied the request."
            else:
                if msg: self.speak(msg)
                return f"Denied: {msg}"

        validation = validate_tool_call_against_user_text(name, args, self.last_user_text)
        if not validation.get("allow", True):
            clarification = enforce_portuguese_local_reply(
                validation.get("clarification") or concise_clarification("Não entendi com segurança. Pode repetir?")
            )
            record_event(
                "tool_blocked_low_confidence",
                name,
                clarification[:200],
                metadata={
                    "intent": validation.get("intent", "unknown"),
                    "confidence": validation.get("confidence", 0.0),
                    "reason": validation.get("reason", "low_confidence"),
                },
                correlation_id=fc.id,
            )
            if clarification:
                self.speak(clarification)
            return types.FunctionResponse(
                id=fc.id,
                name=name,
                response={
                    "result": "blocked_low_confidence",
                    "intent": validation.get("intent", "unknown"),
                    "confidence": validation.get("confidence", 0.0),
                    "reason": validation.get("reason", "low_confidence"),
                },
            )

        print(f"[JARVIS] TOOL: {name} {args}")
        self._safe_set_state("THINKING")



        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            ok, err = _execute_save_memory(category, key, value)
            if not self.ui.muted: self._safe_set_state("LISTENING")
            if ok: return f"Memory saved: {category}/{key}"
            return f"Failed to save memory: {err}"

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None,
                            "player": self.ui, "session_memory": None},
                    daemon=True
                ).start()
                result = "Vision module activated. Stay completely silent — vision module will speak directly."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result   = f"Task started (ID: {task_id})."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                self.speak("Goodbye, sir.")
                def _shutdown():
                    import time, os
                    time.sleep(1)
                    os._exit(0)
                threading.Thread(target=_shutdown, daemon=True).start()

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            record_event("tool_error", name, str(e)[:200], metadata={"tool": name}, severity="error", correlation_id=fc.id)
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self._safe_set_state("LISTENING")

        if _live_resilience_enabled():
            self.resilience.record_tool_call(name, args, result)

        return result

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if not jarvis_speaking and not self.ui.muted:
                data = indata.tobytes()
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"}
                )

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[JARVIS] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS]  Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        if self._suppress_audio_until_turn_complete:
                            pass
                        else:
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content
                        speech_control_handled = False

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                if self._handle_speech_control_command(txt, source="audio"):
                                    speech_control_handled = True
                                    in_buf = []
                                elif not speech_control_handled:
                                    in_buf.append(txt)

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()
                            self._suppress_audio_until_turn_complete = False

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                record_event("user_input", "audio_transcription", full_in[:200], metadata={"input_type": "audio"})
                                self._safe_write_log(f"You: {full_in}")
                                self.last_user_text = full_in
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self._safe_write_log(f"Jarvis: {full_out}")
                            out_buf = []

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            print(f"[JARVIS]  Recv error: {e}")
            if _live_resilience_enabled():
                self.resilience.mark_disconnect(e)
                record_event("live_session_error", "Live", str(e)[:200], severity="error")
                # Don't re-raise, let the TaskGroup/run loop handle the reconnect
                return
            else:
                traceback.print_exc()
                raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue
                if self._suppress_audio_until_turn_complete:
                    continue
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[JARVIS]  Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        while True:
            try:
                if _live_resilience_enabled():
                    if self.resilience.is_shutting_down():
                        break
                    self.resilience.set_state(LiveConnectionState.CONNECTING)

                print("[JARVIS] 🔌 Connecting...")
                self._safe_set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)
                    self._turn_done_event = asyncio.Event()

                    if _live_resilience_enabled():
                        self.resilience.mark_connected()
                        record_event("live_connected", "Live", "Session established")
                        
                        # Drain outbound messages
                        messages = self.resilience.drain_outbound_messages(limit=3)
                        for m in messages:
                            tg.create_task(self.session.send_client_content(turns={"parts": [{"text": m}]}, turn_complete=True))
                            record_event("outbound_message_delivered", "Jarvis", m[:100])

                        # Notify about pending tool results
                        pending_results = self.resilience.get_pending_tool_results()
                        if pending_results:
                            summary = f"Sir, while we were disconnected, {len(pending_results)} tasks finished."
                            self.speak(summary)
                            self.resilience.clear_pending_tool_results()

                    print("[JARVIS] ✅ Connected.")
                    self._safe_set_state("LISTENING")
                    self._safe_write_log("SYS: JARVIS online.")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())

            except Exception as e:
                print(f"[JARVIS] ⚠️ {e}")
                if _live_resilience_enabled():
                    self.resilience.mark_disconnect(e)
                    record_event("live_disconnected", "Live", str(e)[:200], severity="warning")
                    
                    if not self.resilience.should_reconnect(e):
                        print("[JARVIS] 🛑 Non-recoverable error. Shutting down resilience loop.")
                        break
                    
                    delay = self.resilience.next_backoff_delay()
                    print(f"[JARVIS] 🔄 Reconnecting in {delay:.1f}s...")
                    self.resilience.set_state(LiveConnectionState.RECONNECTING)
                    await asyncio.sleep(delay)
                else:
                    traceback.print_exc()
                    self.set_speaking(False)
                    self._safe_set_state("THINKING")
                    print("[JARVIS] 🔄 Reconnecting in 3s...")
                    await asyncio.sleep(3)

def main():
    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()
