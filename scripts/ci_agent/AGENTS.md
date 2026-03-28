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
- If an attempt should be discarded, `controller` should issue an explicit rollback request instead of only describing rollback in text.
- If the current validated state is sufficient, `controller` should issue an explicit done request instead of only describing completion in text.
- `controller` keeps a persistent memory file for strategy, discarded paths, and next-step criteria.
- `validator` keeps a persistent memory file that records the latest validated repo state and recent execution history.
- When `controller` learns something worth preserving, it should record controller memory before that context can be lost to long-running exploration.
- On a fresh session or whenever validator memory is stale, `controller` should ask `validator` to run first.
- After any meaningful code change, `controller` should ask `validator` to run again before deciding whether to keep or discard the attempt.
- Explore boldly and verify carefully. Do not lock onto a direction without evidence.

## Optimization Order

- First make the target command pass.
- Then reduce runtime while preserving behavior.
- Then improve code quality and maintainability without regressing behavior or speed materially.
- Stop when more work is low value or risky.
- These goals may be pursued through local fixes, architecture changes, dependency changes, model/provider changes, caching, batching, concurrency, or pipeline strategy changes.

## Fixer Rules

- Prefer the smallest sufficient change over the smallest possible diff.
- If the best path is architectural, dependency-related, or model/provider-related, a broader change is allowed.
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
- `task` should explicitly compare architecture options, dependency replacements, and model/provider changes when those may unlock PASS, SPEED, or QUALITY gains.
- `task` should keep exploratory shell work inside the dedicated analysis workspace, not in the main repository.
- `task` should return findings, tradeoffs, and concrete next-step recommendations instead of vague brainstorming.

## Controller Rules

- `controller` should not be mechanically conservative.
- If a dependency swap, architecture refactor, or audio-model/provider change is the strongest path, `controller` should allow it.
- `controller` should prefer the smallest sufficient intervention, not the smallest possible diff.
- `controller` should keep its own durable strategy notes: current objective, strongest evidence, discarded options, and next focus.
- Before a long exploratory branch, before declaring done, and before requesting rollback, `controller` should update controller memory with the latest strategic state.
- `controller` should request rollback explicitly when the current attempt should be discarded; Python will execute the rollback safely.
- `controller` should request done explicitly when the current validated state is good enough; Python will perform legality checks and finalize the session.

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
