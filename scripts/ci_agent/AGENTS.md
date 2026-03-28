# CI Agent Runbook

You are maintaining the Xiaohongshu video post pipeline.

## Objective

- Work in layers.
- First make the target command pass.
- Then optimize runtime only if the target command already passes.
- Then improve code quality only if the target command stays green and speed work has reached diminishing returns.
- Stop when additional edits are low value or risky.
- Operate only inside the dedicated CI agent worktree branch.

## Pipeline Context

The video pipeline phases are:

1. research
2. download
3. dub
4. content
5. cover
6. publish

Common technologies in this repository:

- `uv`
- `pydantic-ai`
- Playwright / MCP
- `yt-dlp`
- Whisper / `faster-whisper`
- FFmpeg
- TTS providers

## Editing Rules

- Prefer narrow edits over refactors.
- Read relevant files before editing them.
- Re-read changed files after editing.
- Do not make speculative cleanup changes.
- Keep comments brief and only where they prevent confusion.

## Dependency Rules

- Use `uv add`, `uv remove`, and `uv sync` when dependencies must change.
- Do not use `pip install`.
- Avoid dependency changes unless the failure clearly requires them.

## Git Rules

- You are not on `main`; you are in an isolated worktree branch.
- Never run `git add .`.
- Stage only the files you intentionally changed.
- Commit only when the fix is coherent enough to keep.
- Commit message format: `fix(<scope>): <description>`.

## Validation Mindset

- The next run is the real signal.
- If the root cause is unchanged, the fix should be discarded.
- If the system advanced or the failure changed materially, that is progress.
- Higher-order optimization must never break a passing target command.
- Speed work should prefer measurable runtime wins.
- Quality work should prefer clearer, safer, easier-to-maintain code without speculative refactors.
