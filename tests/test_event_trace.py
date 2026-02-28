import json
import time
from pathlib import Path

from gtos.core.event_bus import EventBus
from gtos.core.events import EventName, RuntimeEvent, TaskPromptActionPayload, event_from_dict, event_to_dict
from gtos.observability.event_trace import EventTraceReplayer
from gtos.plugins.event_recorder_plugin import EventRecorderPlugin


def test_event_roundtrip_dict() -> None:
    ev = RuntimeEvent(name=EventName.ON_ACTION, payload=TaskPromptActionPayload(task_prompt="hello"))
    obj = event_to_dict(ev)
    restored = event_from_dict(obj)
    assert restored.name == EventName.ON_ACTION
    assert isinstance(restored.payload, TaskPromptActionPayload)
    assert restored.payload.task_prompt == "hello"


def test_event_recorder_and_replay_summary() -> None:
    trace = Path(f"data/_unit_events_{int(time.time() * 1000)}.jsonl")
    bus = EventBus()
    rec = EventRecorderPlugin(trace_file=str(trace), enabled=True)
    bus.subscribe(EventName.ON_ACTION, lambda event: rec.on_event(event))
    bus.emit_name(EventName.ON_ACTION, TaskPromptActionPayload(task_prompt="a"))
    bus.emit_name(EventName.ON_ACTION, TaskPromptActionPayload(task_prompt="b"))
    assert trace.exists()

    tool = EventTraceReplayer(trace)
    summary = tool.summary()
    assert summary["total"] == 2
    assert summary["by_event"].get("on_action") == 2
    recent = tool.recent(limit=1)
    assert len(recent) == 1
    assert recent[0]["name"] == "on_action"

    rows = trace.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 2
    obj = json.loads(rows[0])
    assert obj["name"] == "on_action"
