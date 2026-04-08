# Image Post Feishu Review Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `workshop/image_post` send final generated content to Feishu by default instead of publishing to Xiaohongshu, while preserving an explicit publish path.

**Architecture:** Keep the existing `XHSImagePostPipeline` untouched and change only the runner entrypoints. `workshop/image_post/run.py` becomes the source of truth for the default mode and explicit publish flag, and `workshop/image_post/run.ps1` mirrors that CLI contract.

**Tech Stack:** Python argparse runner, PowerShell wrapper, existing Feishu notifier flow

---

## File map

- Modify: `workshop/image_post/run.py`
- Modify: `workshop/image_post/run.ps1`
- Reference only: `workshop/mixed/run.py`
- Reference only: `docs/superpowers/specs/2026-04-08-image-post-feishu-review-default-design.md`

### Task 1: Change Python runner default to Feishu review mode

**Files:**
- Modify: `workshop/image_post/run.py`
- Test: `workshop/image_post/run.py`

- [ ] **Step 1: Update CLI arguments to expose explicit publish mode**

In `parse_args()`:
- add `--publish` as `store_true`
- keep `--feishu-only` for compatibility
- update help text so default behavior is clearly Feishu review, not Xiaohongshu publish

Expected: CLI contract supports explicit publish and documents new default.

- [ ] **Step 2: Change the publish decision in batch execution**

In `run_batch(args)` replace:

```python
publish=not args.feishu_only,
```

with logic equivalent to:

```python
publish=args.publish,
```

while allowing `--feishu-only` to remain harmless compatibility input.

Expected: default run uses `publish=False`; `--publish` uses `publish=True`.

- [ ] **Step 3: Keep success-notification vs review-content branching unchanged**

Do not change `run_single(...)` success handling beyond what is needed for the new default. The existing behavior should remain:
- `publish=True` → publish to Xiaohongshu, then send success notification to Feishu
- `publish=False` → send full generated content to Feishu

Expected: only the default mode changes, not the downstream branching behavior.

- [ ] **Step 4: Read the updated sections back and verify argument flow**

Verify in `run.py`:
- `--publish` exists
- default mode does not imply publish
- `run_batch(...)` passes the expected boolean into `run_single(...)`

Expected: Python entrypoint semantics match the spec.

### Task 2: Align PowerShell wrapper with the new default

**Files:**
- Modify: `workshop/image_post/run.ps1`
- Test: `workshop/image_post/run.ps1`

- [ ] **Step 1: Add an explicit PowerShell publish switch**

In the `param(...)` block add:

```powershell
[switch]$Publish = $false
```

Expected: wrapper has a clear explicit publish control.

- [ ] **Step 2: Forward publish intent to Python only when requested**

When building `$pyArgs`:
- keep existing forwarding behavior for shared args
- append `--publish` only when `$Publish` is set
- do not append `--feishu-only` by default

Expected: wrapper defaults to Feishu review and only publishes when `-Publish` is passed.

- [ ] **Step 3: Read the wrapper back and verify CLI parity**

Verify:
- default wrapper run does not forward `--publish`
- `-Publish` forwards `--publish`
- existing `-NoFeishu` behavior remains intact

Expected: PowerShell and Python entrypoints behave consistently.

### Task 3: Final verification and handoff

**Files:**
- Reference: `workshop/image_post/run.py`
- Reference: `workshop/image_post/run.ps1`

- [ ] **Step 1: Verify only entrypoints changed**

Confirm no edits were made to pipeline internals or mixed runner files.

Expected: change scope stays minimal.

- [ ] **Step 2: Summarize the new operator behavior**

Include:
- default Python command now sends content to Feishu review
- `--publish` enables real Xiaohongshu publishing
- default PowerShell command now sends content to Feishu review
- `-Publish` enables real Xiaohongshu publishing

Expected: user can immediately run the desired mode.

- [ ] **Step 3: Do not commit unless the user asks**

Expected: local file changes only.
