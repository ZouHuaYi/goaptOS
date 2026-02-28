# Event Schema

GTOS runtime now uses typed events (`RuntimeEvent`) instead of raw dictionaries.

## Core Events

- `on_task_start` -> `TaskStartPayload { plugins }`
- `on_plan_generated` -> `PlanGeneratedPayload { task, dag_nodes, policy }`
- `on_thought` -> `ThoughtPayload { task, thought, step, agent }`
- `on_action` -> `TaskPromptActionPayload` or `ActionPayload`
- `on_execution_success` -> `ExecutionSuccessPayload { result, task, step }`
- `on_execution_failure` -> `ExecutionFailurePayload { error_info, task, step }`
- `on_reflection_complete` -> `ReflectionCompletePayload { task, reflection, result }`
- `on_task_end` -> `TaskEndPayload { plugins }`

## Recorder & Replay

- Enable recorder via config:

```json
{
  "plugins": {
    "event_recorder": {
      "enabled": true,
      "trace_file": "data/runtime_events.jsonl"
    }
  }
}
```

- Replay summary:

```bash
python -m gtos.observability.event_trace --trace data/runtime_events.jsonl --summary
```

- Replay events:

```bash
python -m gtos.observability.event_trace --trace data/runtime_events.jsonl
```

