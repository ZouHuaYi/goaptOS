"""Event trace replay and summary tools."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from gtos.core.event_bus import EventBus
from gtos.core.events import RuntimeEvent, event_from_dict


class EventTraceReplayer:
    def __init__(self, trace_file: str | Path) -> None:
        self._trace_file = Path(trace_file)

    def load(self) -> list[RuntimeEvent]:
        return [event_from_dict(r) for r in self.read_rows()]

    def read_rows(self) -> list[dict[str, Any]]:
        if not self._trace_file.exists():
            return []
        out: list[dict[str, Any]] = []
        with open(self._trace_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        out.append(obj)
                except Exception:
                    continue
        return out

    def summary(self) -> dict[str, Any]:
        rows = self.read_rows()
        cnt = Counter([str((r or {}).get("name", "")) for r in rows if str((r or {}).get("name", ""))])
        return {
            "trace_file": str(self._trace_file.resolve()),
            "total": len(rows),
            "by_event": dict(sorted(cnt.items(), key=lambda x: x[0])),
        }

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.read_rows()
        n = max(1, int(limit))
        return rows[-n:]

    def replay(self, event_bus: EventBus | None = None) -> dict[str, Any]:
        bus = event_bus or EventBus()
        events = [event_from_dict(r) for r in self.read_rows()]
        for ev in events:
            bus.emit(ev)
        return {"replayed": len(events)}


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Replay GTOS runtime events from JSONL trace.")
    parser.add_argument("--trace", required=True, help="trace file path (jsonl)")
    parser.add_argument("--summary", action="store_true", help="print summary only")
    args = parser.parse_args()

    tool = EventTraceReplayer(args.trace)
    if args.summary:
        print(json.dumps(tool.summary(), ensure_ascii=False, indent=2))
        return 0
    out = tool.replay()
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
