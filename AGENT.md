# Design Philosophy

This project favors clear boundaries and predictable orchestration. New agents should be designed
to stay small, composable, and focused on a single responsibility.

## Architecture Principles

- **Vertical slices**: Each capability lives in `src/slices/<slice>/` with its own `agent.py`,
  `prompts.py`, and optional validators/tools.
- **Agent vs workflow**: `agent.py` should execute one task; `workflow.py` owns orchestration,
  persistence, and step-level logging.
- **Shared context**: All workflows accept and return `WorkflowContext` from
  `src/workflows/types.py`. This is the contract for data flow.
- **Async only**: Workflow functions are `async def run(ctx)` and must be awaitable.
- **Prompts in code**: Prompts live in slice `prompts.py` (no YAML). Use
  `src/infra/prompting.py` to render templates.
- **Shared infra**: Cross-cutting utilities (login, prompt rendering) live in `src/infra/`.

## Design Guidelines for New Agents

- **Keep agents small**: Avoid orchestration, file IO, and cross-step flow inside the agent.
- **Expose tools, not flows**: If the agent needs tools, provide them as `Tool` or helper methods.
- **Use validators intentionally**: Put slice-specific validators in the same slice. Reuse shared
  validator bases from `src/validators/`.
- **Preserve message history**: When multi-turn loops are needed, keep history bounded and explicit.
- **Prefer graceful degradation**: If an optional step fails, the workflow should log and continue
  when safe (e.g., image generation).
- **Minimize cross-slice imports**: Flow coordination happens in workflows, not in agents.

## Where to Wire Things

- **Slice workflow**: `src/slices/<slice>/workflow.py` implements `run(ctx)`.
- **Full workflow**: `src/workflows/` orchestrates all slices in order.
- **Entrypoint**: `src/main.py` builds the context and calls `FullWorkflow`.

## Conventions

- **Logging**: Use `get_logger(__name__)` and keep logs structured and phase-based.
- **Paths**: Use `Path` objects; output is under `posts/` via `WorkflowContext.create`.
- **Config**: Read settings from `src/config/settings.py`; avoid hard-coded values.

## Checklist for Adding a New Slice

1. Create `src/slices/<new_slice>/agent.py` and `prompts.py`.
2. Add `src/slices/<new_slice>/workflow.py` with `async def run(ctx)`.
3. Update `src/workflows/__init__.py` to include the new slice.
4. Update `README.md` structure if the slice is user-visible.
