import time
import random
import enum
from typing import List, Optional, Dict, Any, Tuple

class LiveConnectionState(enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTING   = "connecting"
    CONNECTED    = "connected"
    RECONNECTING = "reconnecting"
    DEGRADED     = "degraded"
    SHUTTING_DOWN = "shutting_down"

class LiveResilienceSupervisor:
    def __init__(self):
        self.state = LiveConnectionState.DISCONNECTED
        self.backoff_sequence = [3, 5, 10, 20, 60]
        self.backoff_index = 0
        self.last_error: Optional[Exception] = None
        self.last_disconnect_time: float = 0
        
        self.outbound_queue: List[Dict[str, Any]] = []
        self.pending_tool_results: List[Dict[str, Any]] = []
        
        # Duplicate tool call guard
        self.last_tool_call: Optional[Dict[str, Any]] = None

    def set_state(self, state: LiveConnectionState):
        self.state = state

    def is_connected(self) -> bool:
        return self.state in [LiveConnectionState.CONNECTED, LiveConnectionState.DEGRADED]

    def is_shutting_down(self) -> bool:
        return self.state == LiveConnectionState.SHUTTING_DOWN

    def mark_connected(self):
        self.state = LiveConnectionState.CONNECTED
        self.reset_backoff()

    def mark_disconnect(self, error: Exception | None):
        self.last_error = error
        self.last_disconnect_time = time.time()
        if self.state != LiveConnectionState.SHUTTING_DOWN:
            self.state = LiveConnectionState.DISCONNECTED

    def reset_backoff(self):
        self.backoff_index = 0

    def next_backoff_delay(self) -> float:
        if self.backoff_index < len(self.backoff_sequence):
            delay = self.backoff_sequence[self.backoff_index]
            self.backoff_index += 1
        else:
            delay = self.backoff_sequence[-1]
        
        # Add small jitter (±10%)
        jitter = delay * 0.1
        return delay + random.uniform(-jitter, jitter)

    def classify_disconnect_error(self, error: Exception) -> bool:
        """Returns True if the error is recoverable."""
        err_str = str(error).lower()
        
        # Known recoverable errors
        recoverable_patterns = [
            "1011",
            "service is currently unavailable",
            "internal error encountered",
            "connection closed",
            "websocket closed",
            "timeout",
            "network is unreachable",
            "connection reset",
            "remote end closed",
            "server disconnected",
            "unavailable",
            "temporary",
            "internal_error"
        ]
        
        # Known non-recoverable errors
        non_recoverable_patterns = [
            "api key invalid",
            "api_key_invalid",
            "permission denied",
            "auth",
            "unauthorized",
            "invalid_argument",
            "not_found", 
            "quota_exceeded"
        ]

        if any(p in err_str for p in non_recoverable_patterns):
            return False

        if any(p in err_str for p in recoverable_patterns):
            return True

        # Default to recoverable with backoff if unknown
        return True

    def should_reconnect(self, error: Exception | None) -> bool:
        if self.state == LiveConnectionState.SHUTTING_DOWN:
            return False
        if error is None:
            return True
        return self.classify_disconnect_error(error)

    def queue_outbound_message(self, text: str, reason: str | None = None):
        # Redact secrets if any (though outbound messages from Jarvis should be safe)
        # We'll just store them for now.
        msg = {
            "text": text,
            "timestamp": time.time(),
            "reason": reason,
            "delivered": False
        }
        # Avoid huge queues
        if len(self.outbound_queue) > 50:
            self.outbound_queue.pop(0)
        self.outbound_queue.append(msg)

    def drain_outbound_messages(self, limit: int | None = None) -> List[str]:
        # Filter messages that are too old (> 5 minutes)
        now = time.time()
        self.outbound_queue = [m for m in self.outbound_queue if now - m["timestamp"] < 300]
        
        if not self.outbound_queue:
            return []
            
        limit = limit or len(self.outbound_queue)
        batch = self.outbound_queue[:limit]
        self.outbound_queue = self.outbound_queue[limit:]
        
        return [m["text"] for m in batch]

    def record_tool_result_pending(self, tool_name: str, result: str, correlation_id: str | None = None):
        res = {
            "tool": tool_name,
            "result": result,
            "correlation_id": correlation_id,
            "timestamp": time.time()
        }
        # Limit pending results
        if len(self.pending_tool_results) > 20:
            self.pending_tool_results.pop(0)
        self.pending_tool_results.append(res)

    def get_pending_tool_results(self) -> List[Dict[str, Any]]:
        return self.pending_tool_results

    def clear_pending_tool_results(self):
        self.pending_tool_results = []

    def check_duplicate_tool_call(self, name: str, args: dict) -> Tuple[bool, Optional[str]]:
        """
        Returns (is_duplicate, previous_result)
        Protects against repeating the same tool with same args after recent failure.
        """
        now = time.time()
        args_str = str(sorted(args.items())) if args else "{}"
        call_sig = f"{name}:{args_str}"
        
        if self.last_tool_call:
            last_sig = self.last_tool_call["sig"]
            last_time = self.last_tool_call["time"]
            last_res = self.last_tool_call["result"]
            
            # If same call within 10 seconds and it was a "soft failure" or "unavailable"
            if call_sig == last_sig and (now - last_time < 10):
                res_low = str(last_res).lower()
                soft_failures = ["not found", "não foi encontrado", "ambiguous", "broken", "stale", "unavailable", "internal error"]
                if any(f in res_low for f in soft_failures):
                    return True, last_res
                    
        return False, None

    def record_tool_call(self, name: str, args: dict, result: str):
        args_str = str(sorted(args.items())) if args else "{}"
        self.last_tool_call = {
            "sig": f"{name}:{args_str}",
            "time": time.time(),
            "result": result
        }
