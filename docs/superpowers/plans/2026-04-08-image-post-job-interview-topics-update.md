# Image Post Job Interview Topics Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Archive the current `workshop/image_post/topics.json` and replace it with exactly 8 job-search/interview themed topics matching the approved spec.

**Architecture:** This change is data-only. Preserve the current JSON schema and sequential consumption behavior by copying the existing file into a dated history snapshot, then overwrite the active queue with a new 8-item array in the exact required order. Validate structure after writing instead of changing runtime code.

**Tech Stack:** JSON data files, existing Python runner expectations in `workshop/image_post/run.py`

---

## File map

- Modify: `workshop/image_post/topics.json`
- Create: `workshop/image_post/history/topics-2026-04-07.json`
- Reference only: `workshop/image_post/run.py:111-118`
- Reference only: `docs/superpowers/specs/2026-04-07-image-post-job-interview-design.md`

### Task 1: Archive current topics queue

**Files:**
- Create: `workshop/image_post/history/topics-2026-04-07.json`
- Modify: none
- Test: compare archive contents against pre-change `workshop/image_post/topics.json`

- [ ] **Step 1: Read the current topics file and preserve its exact contents in memory**

Read: `workshop/image_post/topics.json`
Expected: existing JSON array with the current non-job-interview topics.

- [ ] **Step 2: Ensure the history directory exists**

Run: create `workshop/image_post/history/` if missing.
Expected: archive parent directory exists.

- [ ] **Step 3: Write the archive snapshot**

If `workshop/image_post/history/topics-2026-04-07.json` already exists, overwrite it with the new pre-change snapshot.

Write the exact pre-change contents to:
`workshop/image_post/history/topics-2026-04-07.json`

Expected: file contents are a direct copy of the original source snapshot.

- [ ] **Step 4: Verify the archive file was written correctly**

Check:
- file exists
- parsed JSON is a list
- full parsed JSON equals the full pre-change snapshot from `workshop/image_post/topics.json`

Expected: archive is a faithful full copy of the old queue.

### Task 2: Replace active topics queue with 8 interview topics

**Files:**
- Modify: `workshop/image_post/topics.json`
- Test: validate JSON schema and topic ordering

- [ ] **Step 1: Draft the 8 replacement objects in the exact approved order**

Order must be:
1. 个人叙事 / 自我介绍埋钩子
2. 群面 / 压力面拆解
3. 面试官视角 / 判断维度 / 潜台词
4. 缺点包装 / 被质疑时的回答
5. 模拟面试
6. 反问环节
7. 面试复盘
8. offer call 谈薪

Each object must contain exactly these keys:
- `topic`
- `audience`
- `strategy`
- `format`
- `priority`

Content rules:
- strictly job-search / interview tips only
- Chinese publish-ready titles
- concrete audience
- 1-2 sentence strategy
- `format` in short tag style
- `priority` only `P0` or `P1`

- [ ] **Step 2: Overwrite `workshop/image_post/topics.json` with the new 8-item array**

Write a complete JSON array containing only the new 8 topic objects.
Expected: old queue is fully replaced.

- [ ] **Step 3: Read the rewritten file back**

Read: `workshop/image_post/topics.json`
Expected: 8 entries in the approved order.

- [ ] **Step 4: Validate structure and constraints**

Verify:
- valid JSON array
- exactly 8 objects
- entries appear in the exact approved order from the spec
- each object has exactly 5 keys: `topic`, `audience`, `strategy`, `format`, `priority`
- all `priority` values are `P0` or `P1`
- each topic maps 1:1 to one approved direction
- no unrelated泛职场/穿搭/鸡汤内容

Expected: file matches the spec and remains compatible with `workshop/image_post/run.py`.

### Task 3: Final verification and handoff

**Files:**
- Reference: `workshop/image_post/history/topics-2026-04-07.json`
- Reference: `workshop/image_post/topics.json`

- [ ] **Step 1: Compare archive and active files conceptually**

Confirm:
- archive holds the old queue
- active file holds the new queue
- the two files are intentionally different

Expected: history preserved and active queue updated.

- [ ] **Step 2: Summarize the completed change for the user**

Include:
- archive path
- active file path
- note that runtime code was unchanged
- short list of the 8 new theme directions

Expected: user can immediately see what changed and where.

- [ ] **Step 3: Do not commit unless the user asks**

Expected: local file changes only.
