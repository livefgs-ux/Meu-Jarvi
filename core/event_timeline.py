import json
import time
import uuid
import os
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

@dataclass
class EventRecord:
    event_id: str
    timestamp: float
    event_type: str
    source: str
    summary: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    severity: str = "info"
    correlation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class EventTimeline:
    def __init__(self, max_events: int = 1000):
        self.max_events = max_events
        self.events: List[EventRecord] = []
        self._secret_patterns = [
            re.compile(r'api_key', re.I),
            re.compile(r'password', re.I),
            re.compile(r'token', re.I),
            re.compile(r'secret', re.I),
            re.compile(r'key', re.I),
        ]
        self._sensitive_regex = re.compile(r'(?i)(api[_-]?key|password|token|secret|auth|bearer)\s*[:=]\s*["\']?([a-zA-Z0-9_\-\.\/]+)["\']?')

    def add_event(
        self, 
        event_type: str, 
        source: str, 
        summary: str, 
        metadata: Optional[Dict[str, Any]] = None, 
        severity: str = "info", 
        correlation_id: Optional[str] = None
    ) -> EventRecord:
        
        # Redact secrets
        clean_summary = self._redact_text(summary)
        clean_metadata = self._redact_metadata(metadata or {})
        
        # Limit metadata size
        clean_metadata = self._limit_metadata_size(clean_metadata)

        record = EventRecord(
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            event_type=event_type,
            source=source,
            summary=clean_summary,
            metadata=clean_metadata,
            severity=severity,
            correlation_id=correlation_id
        )

        self.events.append(record)
        
        # Ring buffer enforcement
        if len(self.events) > self.max_events:
            self.events.pop(0)
            
        return record

    def list_recent(self, limit: Optional[int] = None, event_type: Optional[str] = None) -> List[EventRecord]:
        filtered = self.events
        if event_type:
            filtered = [e for e in filtered if e.event_type == event_type]
        
        if limit:
            return filtered[-limit:]
        return filtered

    def find_recent(
        self, 
        event_type: Optional[str] = None, 
        source: Optional[str] = None, 
        correlation_id: Optional[str] = None
    ) -> List[EventRecord]:
        results = self.events
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        if source:
            results = [e for e in results if e.source == source]
        if correlation_id:
            results = [e for e in results if e.correlation_id == correlation_id]
        return results

    def clear(self):
        self.events = []

    def to_dict(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self.events]

    def export_jsonl(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for e in self.events:
                f.write(json.dumps(e.to_dict()) + "\n")

    def load_jsonl(self, path: str):
        if not os.path.exists(path):
            return
        
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    record = EventRecord(**data)
                    self.events.append(record)
                    if len(self.events) > self.max_events:
                        self.events.pop(0)
                except Exception:
                    continue

    def _redact_text(self, text: str) -> str:
        if not text:
            return text
        # Simple heuristic redaction
        return self._sensitive_regex.sub(r'\1: [REDACTED]', text)

    def _redact_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        clean = {}
        for k, v in metadata.items():
            is_sensitive = any(p.search(k) for p in self._secret_patterns)
            if is_sensitive:
                clean[k] = "[REDACTED]"
            elif isinstance(v, dict):
                clean[k] = self._redact_metadata(v)
            elif isinstance(v, str):
                clean[k] = self._redact_text(v)
            else:
                clean[k] = v
        return clean

    def _limit_metadata_size(self, metadata: Dict[str, Any], max_len: int = 1024) -> Dict[str, Any]:
        limited = {}
        for k, v in metadata.items():
            if isinstance(v, str) and len(v) > max_len:
                limited[k] = v[:max_len] + "... [TRUNCATED]"
            elif isinstance(v, dict):
                limited[k] = self._limit_metadata_size(v, max_len)
            else:
                limited[k] = v
        return limited

DEFAULT_TIMELINE_PATH = ".local_state/environment_timeline.jsonl"
