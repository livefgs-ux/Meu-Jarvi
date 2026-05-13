# Actions and Tools (Local)

This document maps the actions/tools that exist in the local repository.

Note: availability depends on OS, permissions, installed dependencies, and local configuration. Some actions are experimental.

## Runtime Tool Calling
The runtime defines a tool/function calling interface and routes calls to the action implementations in `actions/`.

## actions/
Observed modules (non-exhaustive list based on local folder contents):
- `open_app.py`: open/launch applications.
- `browser_control.py`: browser automation/control.
- `desktop.py`: desktop-level controls.
- `computer_control.py`: screen find/click and related controls.
- `computer_settings.py`: OS/system settings actions.
- `file_controller.py`: file operations (move/copy/delete/etc.) - should be used with caution.
- `file_processor.py`: processing/analyzing user-provided files.
- `screen_processor.py`: screen processing/vision pipeline integration.
- `send_message.py`: messaging action integration.
- `reminder.py`: reminders.
- `weather_report.py`: weather reporting.
- `web_search.py`: web search action (runtime may call it depending on tool routing).
- `youtube_video.py`: YouTube-related actions.
- `code_helper.py`: code assistance helper action.
- `dev_agent.py`: developer helper agent action.
- `flight_finder.py`: flight finder action.
- `game_updater.py`: game-related updater/install logic (should remain scoped to games).

## agent/
Task execution support:
- `task_queue.py`: queueing and running tasks.
- `planner.py`: planning.
- `executor.py`: execution.
- `error_handler.py`: error handling.

## tools/
Developer/operator tools (manual surfaces):
- `tools/memory_cli.py`: manual Memory Engine CLI (init/add/list/search/show/set-status/archive/audit/context).
- `tools/memory_context_preview.py`: read-only preview harness for the bounded runtime memory prompt block.

## Non-Goals
- This document does not claim all actions are safe for unattended execution.
- This document does not imply the system is fully autonomous.

