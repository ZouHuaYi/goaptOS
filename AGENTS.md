# Repository Guidelines

## Project Structure & Module Organization
- `gtos/` contains the Python package.
- `gtos/main.py` is the CLI entry (`python -m gtos.main`) and runtime wiring.
- `gtos/core/` holds LLM abstractions; `gtos/executor/` contains planning/DAG/execution flow.
- `gtos/plugins/` contains extension hooks (`logger`, `skill`, `agent`, `llm_optimizer`).
- `gtos/memory/` contains vector/SQLite memory backends.
- `data/` stores runtime artifacts (for example `skills.json`, `skill_vectors.json`, `gtos.db`).
- `docs/` stores design and roadmap docs.

## Build, Test, and Development Commands
- `pip install -e .` installs the project in editable mode.
- `python -m gtos.main` runs the default task from `config.json`.
- `python -m gtos.main --task "print hello"` runs a one-off task.
- `python -m gtos.main --config config.custom.json` runs with alternate config.
- `run.cmd` Windows shortcut for `python -m gtos.main %*`.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and clear type hints (this codebase already uses typed signatures).
- Use `snake_case` for functions/variables, `PascalCase` for classes, and short module names by domain (`planner.py`, `dag_runner.py`).
- Keep plugin behavior isolated per file under `gtos/plugins/`.
- Prefer small, composable functions and explicit error handling (see `main.py` flow).

## Testing Guidelines
- There is no committed test suite yet (`tests/` is absent).
- For changes, add targeted tests under a new `tests/` package using `pytest` (`tests/test_<module>.py`).
- Minimum expectation for PRs: run at least one end-to-end smoke check:
  - `python -m gtos.main --task "用 Python 计算 1+2 并打印结果"`
- If changing planner/plugins/memory, include one regression test per changed behavior.

## Commit & Pull Request Guidelines
- Git history is not available in this workspace snapshot, so no enforceable historical commit pattern could be derived.
- Use Conventional Commits going forward (for example `feat: add chroma backend fallback logging`).
- PRs should include: purpose, key changes, how to run/verify, config impacts, and sample output when behavior changes.
- Link related issues/tasks and call out breaking changes explicitly.

## Security & Configuration Tips
- Keep secrets out of `config.json`; use environment variables (for example `OPENAI_API_KEY`).
- Treat `data/` as runtime state; avoid committing machine-local DB/vector artifacts unless intentionally updating fixtures.
