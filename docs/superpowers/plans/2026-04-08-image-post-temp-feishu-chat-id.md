# Image Post Temporary Feishu Chat ID Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a batch-scoped Feishu chat ID override to `workshop/image_post` so this runner can send review or publish notifications to a temporary target chat without changing `.env` or any persistent config.

**Architecture:** Keep `FeishuNotifier` and `FeishuConfig.CHAT_ID` unchanged. Thread an optional `feishu_chat_id` value from the Python and PowerShell entrypoints down to the exact `send_message(...)` and `send_image(...)` calls in `workshop/image_post/run.py`, so the override is explicit, local to the current batch, and absent by default.

**Tech Stack:** Python argparse runner, asyncio, PowerShell wrapper, pytest, importlib-based CLI module loading, monkeypatch fakes

---

## File map

- Modify: `workshop/image_post/run.py` — add `--feishu-chat-id`, normalize the optional override, and pass it into every Feishu send call triggered by this runner
- Modify: `workshop/image_post/run.ps1` — add `-FeishuChatId` and forward `--feishu-chat-id <value>` only when provided
- Create: `tests/test_image_post_runner_cli.py` — targeted regression tests for CLI parsing, batch argument flow, and Feishu send-call forwarding
- Reference: `docs/superpowers/specs/2026-04-08-image-post-temp-feishu-chat-id-design.md`
- Reference only: `src/utils/feishu_notifier.py` — confirm default chat resolution remains unchanged

### Task 1: Add focused regression tests for the image_post runner

**Files:**
- Create: `tests/test_image_post_runner_cli.py`
- Reference: `tests/test_dub_video_cli.py`
- Reference: `workshop/image_post/run.py`

- [ ] **Step 1: Write a loader helper that imports `workshop/image_post/run.py` with fake heavy dependencies**

Add a helper that mirrors the `importlib.util.spec_from_file_location(...)` style from `tests/test_dub_video_cli.py`, but injects lightweight fakes for `logfire`, `src.agents.image_post`, `src.utils.logger`, and `src.utils.feishu_notifier` before import so the test can exercise the runner without booting the real pipeline.

```python
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _load_image_post_runner(monkeypatch):
    fake_logfire = SimpleNamespace(
        configure=lambda **kwargs: None,
        instrument_pydantic_ai=lambda: None,
    )

    fake_agent_module = ModuleType("src.agents.image_post")

    class _FakeInput:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _FakePipeline:
        async def execute(self, _input):
            raise AssertionError("pipeline should not run in CLI unit tests")

    fake_agent_module.XHSImagePostInput = _FakeInput
    fake_agent_module.XHSImagePostPipeline = _FakePipeline

    fake_logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        exception=lambda *args, **kwargs: None,
    )
    fake_logger_module = ModuleType("src.utils.logger")
    fake_logger_module.setup_logging = lambda: None
    fake_logger_module.get_logger = lambda _name: fake_logger

    fake_notifier_module = ModuleType("src.utils.feishu_notifier")
    fake_notifier_module.get_feishu_notifier = lambda: None

    monkeypatch.setitem(sys.modules, "logfire", fake_logfire)
    monkeypatch.setitem(sys.modules, "src.agents.image_post", fake_agent_module)
    monkeypatch.setitem(sys.modules, "src.utils.logger", fake_logger_module)
    monkeypatch.setitem(sys.modules, "src.utils.feishu_notifier", fake_notifier_module)

    script_path = Path(__file__).resolve().parents[1] / "workshop" / "image_post" / "run.py"
    spec = importlib.util.spec_from_file_location("image_post_runner_cli", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```

- [ ] **Step 2: Write a failing CLI parse test for `--feishu-chat-id`**

Add a test that patches `sys.argv`, calls `parse_args()`, and proves the new option is captured.

```python
def test_image_post_runner_parse_args_accepts_feishu_chat_id(monkeypatch) -> None:
    module = _load_image_post_runner(monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--feishu-chat-id",
            "oc_34e4d2807836899d83d87c71a4db439f",
        ],
    )

    args = module.parse_args()

    assert args.feishu_chat_id == "oc_34e4d2807836899d83d87c71a4db439f"
```

- [ ] **Step 3: Write a failing review-send test that requires forwarding `chat_id` to every Feishu call**

Use a fake notifier that records every `send_message(...)` and `send_image(...)` call. Create a temporary `content.json` and one fake image path, then call `send_content_to_feishu(...)` with an override.

```python
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


class _RecordingNotifier:
    def __init__(self) -> None:
        self.messages = []
        self.images = []

    async def send_message(self, text: str, chat_id: str | None = None, parse_mode=None):
        self.messages.append({"text": text, "chat_id": chat_id})

    async def send_image(self, image_path: Path, caption: str = "", chat_id: str | None = None):
        self.images.append({"path": Path(image_path), "caption": caption, "chat_id": chat_id})


@pytest.mark.asyncio
async def test_send_content_to_feishu_forwards_override_to_all_messages_and_images(monkeypatch, tmp_path: Path) -> None:
    module = _load_image_post_runner(monkeypatch)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(module, "get_feishu_notifier", lambda: notifier)

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "content.json").write_text(
        json.dumps({"body": "正文内容"}, ensure_ascii=False),
        encoding="utf-8",
    )
    image_path = output_dir / "cover.png"
    image_path.write_bytes(b"fake")

    result = SimpleNamespace(
        output_dir=str(output_dir),
        title="测试标题",
        hashtags=["#测试"],
        image_paths=[str(image_path)],
    )

    await module.send_content_to_feishu(
        result,
        "测试主题",
        feishu_chat_id="oc_34e4d2807836899d83d87c71a4db439f",
    )

    assert notifier.messages
    assert notifier.images
    assert {item["chat_id"] for item in notifier.messages} == {"oc_34e4d2807836899d83d87c71a4db439f"}
    assert {item["chat_id"] for item in notifier.images} == {"oc_34e4d2807836899d83d87c71a4db439f"}
```

- [ ] **Step 4: Write a failing publish-notification test for `run_single(...)`**

Drive `run_single(...)` through a fake successful publish result and assert both the success message and cover image preview receive the override.

```python
@pytest.mark.asyncio
async def test_run_single_forwards_override_to_publish_success_notifications(monkeypatch) -> None:
    module = _load_image_post_runner(monkeypatch)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(module, "get_feishu_notifier", lambda: notifier)

    class _FakeResult:
        success = True
        published = True
        title = "测试标题"
        hashtags = ["#测试"]
        image_count = 1
        post_url = "https://example.com/post"
        image_paths = ["cover.png"]
        output_dir = "unused"

        def model_dump(self):
            return {"success": True}

    class _FakePipeline:
        async def execute(self, _input):
            return _FakeResult()

    monkeypatch.setattr(module, "XHSImagePostPipeline", _FakePipeline)

    result = await module.run_single(
        {"topic": "测试主题", "audience": "测试受众"},
        1,
        1,
        1,
        0,
        publish=True,
        notify_feishu=True,
        feishu_chat_id="oc_34e4d2807836899d83d87c71a4db439f",
    )

    assert result["success"] is True
    assert [item["chat_id"] for item in notifier.messages] == ["oc_34e4d2807836899d83d87c71a4db439f"]
    assert [item["chat_id"] for item in notifier.images] == ["oc_34e4d2807836899d83d87c71a4db439f"]
```

- [ ] **Step 5: Write a failing batch-flow test that requires forwarding the normalized override into `run_single(...)`**

Patch `run_single(...)` with a recorder and use a one-item temporary topics file.

```python
import argparse
import json

import pytest


@pytest.mark.asyncio
async def test_run_batch_passes_feishu_chat_id_to_run_single(monkeypatch, tmp_path: Path) -> None:
    module = _load_image_post_runner(monkeypatch)

    topics_file = tmp_path / "topics.json"
    topics_file.write_text(
        json.dumps([
            {"topic": "测试主题", "audience": "测试受众"}
        ], ensure_ascii=False),
        encoding="utf-8",
    )

    seen = {}

    async def _fake_run_single(*args, **kwargs):
        seen["feishu_chat_id"] = kwargs["feishu_chat_id"]
        return {"success": True}

    monkeypatch.setattr(module, "run_single", _fake_run_single)

    args = argparse.Namespace(
        topics_file=topics_file,
        start_index=1,
        limit=None,
        max_retries=1,
        retry_delay=0,
        sleep=None,
        no_feishu=False,
        publish=False,
        feishu_only=False,
        feishu_chat_id=" oc_34e4d2807836899d83d87c71a4db439f ",
    )

    exit_code = await module.run_batch(args)

    assert exit_code == 0
    assert seen["feishu_chat_id"] == "oc_34e4d2807836899d83d87c71a4db439f"
```

- [ ] **Step 6: Write a failing `--no-feishu` edge-case test so the override only affects real send calls**

Clarify the non-goal in executable form: when Feishu sending is disabled, the override is accepted but no Feishu send path runs.

```python
@pytest.mark.asyncio
async def test_run_single_does_not_send_feishu_when_notifications_disabled(monkeypatch) -> None:
    module = _load_image_post_runner(monkeypatch)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(module, "get_feishu_notifier", lambda: notifier)

    class _FakeResult:
        success = True
        published = True
        title = "测试标题"
        hashtags = ["#测试"]
        image_count = 1
        post_url = "https://example.com/post"
        image_paths = ["cover.png"]
        output_dir = "unused"

        def model_dump(self):
            return {"success": True}

    class _FakePipeline:
        async def execute(self, _input):
            return _FakeResult()

    monkeypatch.setattr(module, "XHSImagePostPipeline", _FakePipeline)

    await module.run_single(
        {"topic": "测试主题", "audience": "测试受众"},
        1,
        1,
        1,
        0,
        publish=True,
        notify_feishu=False,
        feishu_chat_id="oc_34e4d2807836899d83d87c71a4db439f",
    )

    assert notifier.messages == []
    assert notifier.images == []
```

- [ ] **Step 7: Run the new test file and confirm it fails for the missing override support**

Run: `uv run pytest tests/test_image_post_runner_cli.py -q`

Expected: failures showing `parse_args()` has no `feishu_chat_id` yet and/or Feishu send calls are not forwarding `chat_id`.

### Task 2: Implement the Python runner override without changing global Feishu defaults

**Files:**
- Modify: `workshop/image_post/run.py`
- Test: `tests/test_image_post_runner_cli.py`
- Reference only: `src/utils/feishu_notifier.py`

- [ ] **Step 1: Add the optional override parameter to the runner helper signatures**

Update both helper signatures so the override can flow through the Python runner explicitly.

```python
async def send_content_to_feishu(
    result: Any,
    topic: str,
    *,
    feishu_chat_id: str | None = None,
) -> None:
    ...


async def run_single(
    item: dict[str, Any],
    idx: int,
    total: int,
    max_retries: int,
    retry_delay: int,
    *,
    publish: bool = True,
    notify_feishu: bool = True,
    feishu_chat_id: str | None = None,
) -> dict[str, Any]:
    ...
```

- [ ] **Step 2: Thread `chat_id=feishu_chat_id` into every Feishu send call in `run.py`**

In `send_content_to_feishu(...)`, update every `send_message(...)` and `send_image(...)` call to pass the explicit keyword argument.

```python
await notifier.send_message(header, chat_id=feishu_chat_id)
...
await notifier.send_message(
    f"--- 正文 (第{part_num}段) ---\n{chunk}",
    chat_id=feishu_chat_id,
)
...
await notifier.send_message(f"{header}{body_section}", chat_id=feishu_chat_id)
...
await notifier.send_image(
    p,
    caption=f"图片 {idx}/{len(image_paths)}",
    chat_id=feishu_chat_id,
)
```

Then update the publish-success branch inside `run_single(...)`.

```python
await notifier.send_message("\n".join(lines), chat_id=feishu_chat_id)
if result.image_paths:
    await notifier.send_image(
        Path(result.image_paths[0]),
        caption="封面图",
        chat_id=feishu_chat_id,
    )
```

And when review mode is used, pass the override through to the helper.

```python
await send_content_to_feishu(
    result,
    topic,
    feishu_chat_id=feishu_chat_id,
)
```

- [ ] **Step 3: Add CLI parsing for `--feishu-chat-id` and normalize blank input back to `None`**

In `parse_args()` add the new option:

```python
p.add_argument(
    "--feishu-chat-id",
    type=str,
    default=None,
    help="临时覆盖本次 batch 的飞书群 chat_id（不修改环境变量）",
)
```

In `run_batch(args)` normalize once before the loop so whitespace-only input does not override the default notifier target.

```python
feishu_chat_id = args.feishu_chat_id.strip() if args.feishu_chat_id else None
if feishu_chat_id == "":
    feishu_chat_id = None
```

- [ ] **Step 4: Pass the normalized override into every `run_single(...)` call**

Update the batch loop call site.

```python
result = await run_single(
    item,
    idx,
    base_idx + total - 1,
    args.max_retries,
    args.retry_delay,
    publish=args.publish and not args.feishu_only,
    notify_feishu=not args.no_feishu,
    feishu_chat_id=feishu_chat_id,
)
```

- [ ] **Step 5: Run the focused tests and confirm they now pass**

Run: `uv run pytest tests/test_image_post_runner_cli.py -q`

Expected: all tests in `tests/test_image_post_runner_cli.py` pass.

### Task 3: Expose the same override in the PowerShell wrapper

**Files:**
- Modify: `workshop/image_post/run.ps1`
- Reference: `workshop/image_post/run.py`

- [ ] **Step 1: Add a new optional `-FeishuChatId` parameter to the wrapper**

Extend the `param(...)` block with an empty-string default so “not provided” remains easy to detect.

```powershell
param(
    [string]$TopicsFile = "",
    [int]$StartIndex = 1,
    [int]$Limit = 0,
    [int]$MaxRetries = 10,
    [int]$RetryDelay = 5,
    [int]$Sleep = 0,
    [switch]$Publish = $false,
    [string]$FeishuChatId = "",
    [switch]$NoFeishu = $false
)
```

- [ ] **Step 2: Forward `--feishu-chat-id` only when the wrapper parameter is non-empty**

Update the `$pyArgs` assembly so the Python runner gets the override only for this invocation.

```powershell
if ($FeishuChatId) {
    $pyArgs += @("--feishu-chat-id", $FeishuChatId)
}
```

Do not inject environment variables and do not change any existing `-NoFeishu` or `-Publish` behavior.

- [ ] **Step 3: Statistically verify the wrapper contains the new parameter and conditional forwarding**

Run:

```bash
uv run python -c "from pathlib import Path; text = Path('workshop/image_post/run.ps1').read_text(encoding='utf-8'); assert '[string]$FeishuChatId = ""' in text; assert '@("--feishu-chat-id", $FeishuChatId)' in text; print('wrapper-ok')"
```

Expected: `wrapper-ok`

### Task 4: Final verification and handoff

**Files:**
- Reference: `workshop/image_post/run.py`
- Reference: `workshop/image_post/run.ps1`
- Reference: `tests/test_image_post_runner_cli.py`
- Reference only: `src/config/settings.py`
- Reference only: `src/utils/feishu_notifier.py`

- [ ] **Step 1: Run the targeted test suite again as the final Python-side verification**

Run: `uv run pytest tests/test_image_post_runner_cli.py -q`

Expected: pass with 0 failures.

- [ ] **Step 2: Re-read the changed files and verify the scope is still narrow**

Confirm all of the following are true:
- `workshop/image_post/run.py` exposes `--feishu-chat-id`
- `workshop/image_post/run.py` forwards the override into publish notifications and review sends
- `workshop/image_post/run.ps1` exposes `-FeishuChatId`
- `workshop/image_post/run.ps1` only forwards `--feishu-chat-id` when the value is present
- `src/config/settings.py` is unchanged
- `src/utils/feishu_notifier.py` default chat resolution is unchanged

- [ ] **Step 3: Summarize the new operator commands without changing any persistent config**

Document these exact commands for handoff:

```bash
uv run python workshop/image_post/run.py --feishu-chat-id oc_34e4d2807836899d83d87c71a4db439f
```

```bash
uv run python workshop/image_post/run.py --publish --feishu-chat-id oc_34e4d2807836899d83d87c71a4db439f
```

```powershell
./workshop/image_post/run.ps1 -FeishuChatId oc_34e4d2807836899d83d87c71a4db439f
```

- [ ] **Step 4: Do not commit unless the user asks**

Expected: local file changes only.
