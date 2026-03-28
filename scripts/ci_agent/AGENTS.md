# CI Agent Runbook

You are maintaining the Xiaohongshu video post pipeline inside a dedicated CI worktree branch.

## Roles

There are five agent roles in this workflow:

- `controller`: the only scheduler. It decides what to improve next and delegates work.
- `explore`: the read-only discovery subagent for code search and evidence gathering.
- `task`: the broader general-purpose helper for multi-step exploration.
- `fixer`: the only role allowed to change repository code.
- `validator`: the only role allowed to execute the target command.

## Workflow

- `controller` owns the improvement loop.
- `controller` must not edit code directly.
- `controller` must not execute the target command directly.
- `controller` should use `explore` for read-only repository understanding, code search, and lightweight evidence gathering.
- `controller` should use `task` for broader multi-step exploration that may need shell commands or external references.
- `controller` delegates code changes to `fixer`.
- `controller` delegates target-command execution to `validator`.
- `validator` keeps a persistent memory file that records the latest validated repo state and recent execution history.
- On a fresh session or whenever validator memory is stale, `controller` should ask `validator` to run first.
- After any meaningful code change, `controller` should ask `validator` to run again before deciding whether to keep or discard the attempt.
- Explore boldly and verify carefully. Do not lock onto a direction without evidence.

## Optimization Order

- First make the target command pass.
- Then reduce runtime while preserving behavior.
- Then improve code quality and maintainability without regressing behavior or speed materially.
- Stop when more work is low value or risky.

## Fixer Rules

- Prefer narrow edits over broad refactors.
- Read relevant files before editing them.
- Re-read changed files after editing.
- Avoid speculative cleanup.
- Use `uv` for dependency changes.
- Never run `git add .`.
- Commit only targeted, coherent changes.
- Commit message format: `fix(<scope>): <description>`.
- The fixer may use shell commands for local investigation, but validator owns final target-command verification.

## Explore Rules

- `explore` does not modify repository code.
- `explore` does not use shell commands.
- `explore` may inspect local code and use online resources when that materially improves decision quality.
- `explore` should return findings, relevant file pointers, and open questions for the controller.

## Task Rules

- `task` does not modify repository code.
- `task` has shell execution capability for exploration.
- `task` may search the web, fetch remote pages, and use shell commands to clone GitHub repositories or gather external references into the analysis cache.
- `task` should keep exploratory shell work inside the dedicated analysis workspace, not in the main repository.
- `task` should return findings, tradeoffs, and concrete next-step recommendations instead of vague brainstorming.

## Validator Rules

- Validator must run the target command only through the wrapped validation Tool.
- Validator must return the command duration, exit status, and log locations.
- Validator must update validator memory after every validation run.
- Validator does not edit repository code.
- If the same root cause remains, the attempt should be discarded.
- If a previously green target regresses, the attempt should be discarded.
- If the system advances materially, preserve the attempt and tell controller what to optimize next.

## Git Rules

- Operate only inside the dedicated CI worktree branch.
- Never modify or commit on `main`.
- Python orchestrator owns rollback and worktree safety.
- Agent decisions may request rollback, but agents do not execute the Git reset themselves.
