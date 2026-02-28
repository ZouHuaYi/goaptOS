"""Record runtime events to JSONL for debugging and replay."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from gtos.core.events import RuntimeEvent, event_to_dict
from gtos.executor.plugin_manager import Plugin


class EventRecorderPlugin(Plugin):
    def __init__(self, trace_file: str = "data/runtime_events.jsonl", enabled: bool = True) -> None:
        self._trace_file = Path(trace_file)
        self._enabled = bool(enabled)
        self._lock = threading.Lock()
        self._trace_file.parent.mkdir(parents=True, exist_ok=True)

    def on_event(self, event: RuntimeEvent) -> None:
        if not self._enabled:
            return
        row = event_to_dict(event)
        row["ts"] = time.time()
        with self._lock:
            with open(self._trace_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

