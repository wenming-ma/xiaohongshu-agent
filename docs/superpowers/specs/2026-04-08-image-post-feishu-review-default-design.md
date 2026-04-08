# workshop/image_post 飞书审核默认化设计

- 日期：2026-04-08
- 范围：`workshop/image_post/run.py`、`workshop/image_post/run.ps1`
- 参考：`workshop/mixed/run.py`

## 目标

将 `workshop/image_post` 的默认执行行为从“直接发布到小红书”调整为“生成最终内容并发送到飞书审核”，使其与 `workshop/mixed` 的审核式使用方式保持一致；同时保留显式发布到小红书的能力，供人工确认后使用。

## 当前行为

### Python 入口

`workshop/image_post/run.py` 当前行为：

- `run_single(..., publish: bool = True)` 默认 `publish=True`
- CLI 仅提供 `--feishu-only`，通过 `publish=not args.feishu_only` 控制
- 默认执行会直接发布到小红书
- 发布成功后只向飞书发送“发布成功通知 + 封面图预览”
- 只有显式使用 `--feishu-only` 时，才会把完整内容（标题、正文、话题、图片）发送到飞书审核

### PowerShell 入口

`workshop/image_post/run.ps1` 当前仅透传 `--no-feishu`，未暴露 `--feishu-only`，因此通过 PowerShell 入口无法方便地进入“只发飞书不发布”的审核模式。

## 设计结论

采用“默认飞书审核，显式发布”的入口层改造方案。

### 方案对比

#### 方案 A：仅修改 PowerShell 包装层
- 优点：改动少
- 缺点：Python 入口默认行为仍是直接发布，两个入口语义不一致

#### 方案 B：修改 Python 与 PowerShell 两个入口（采用）
- 默认不发布到小红书，而是发送完整内容到飞书
- 通过新的显式参数开启真实发布
- 优点：行为清晰、入口一致、最贴合当前使用诉求
- 缺点：需要同步更新两个入口的参数语义

#### 方案 C：修改 pipeline 默认值
- 优点：表面上更“彻底”
- 缺点：会扩大影响面，不利于保持变更局部化

## 采用设计

### 1. 保持 pipeline 不变，仅修改 runner 入口语义

不修改 `XHSImagePostPipeline` 和 `XHSImagePostInput` 的内部发布机制，仅调整 `workshop/image_post/run.py` 与 `workshop/image_post/run.ps1` 如何传入 `publish`。

### 2. Python 入口改为默认飞书审核

在 `workshop/image_post/run.py` 中：

- 新增显式参数 `--publish`
- 保留 `--feishu-only` 作为兼容别名，二者都表达“不要发布到小红书，仅发飞书审核”这一默认方向的反义控制
- 默认情况下 `publish=False`
- 只有显式传入 `--publish` 时，才设置 `publish=True`

这样默认执行：

```bash
uv run python workshop/image_post/run.py
```

行为变为：
- 生成内容
- 将完整内容发送到飞书
- 不发布到小红书

而：

```bash
uv run python workshop/image_post/run.py --publish
```

行为为：
- 正常发布到小红书
- 发布成功后向飞书发送成功通知

### 3. PowerShell 入口与 Python 入口保持一致

在 `workshop/image_post/run.ps1` 中：

- 新增 `-Publish` 开关
- 默认不发布
- 传入 `-Publish` 时，向 Python 入口透传 `--publish`
- 保留已有 `-NoFeishu`

这样默认执行：

```powershell
./workshop/image_post/run.ps1
```

将变为飞书审核流；而：

```powershell
./workshop/image_post/run.ps1 -Publish
```

才是真实发布流。

## 与 workshop/mixed 的一致性

本次一致性的目标是“默认使用飞书审核而不是直接外发”，不是强行复制 `workshop/mixed/run.py` 的所有实现细节。

保持一致的点：
- 不发布时，把完整内容发送到飞书
- 发布时，只发发布成功通知
- runner 层决定是否 publish

不做的事：
- 不重写 `send_content_to_feishu(...)`
- 不抽取共享 runner 基类
- 不修改 mixed 的现有行为

## 兼容性与风险

### 兼容性

- `workshop/image_post/run.py` 的核心执行链不变
- `XHSImagePostPipeline` 无需修改
- 飞书审核链路已存在，只是从“显式触发”变为“默认触发”

### 风险

1. **已有脚本调用者依赖默认直接发布**
   - 规避：新增 `--publish` / `-Publish` 明确表达真实发布意图
2. **参数语义迁移造成误解**
   - 规避：帮助文本明确写出默认行为已变为飞书审核
3. **同时保留 `--feishu-only` 可能产生重复语义**
   - 规避：实现时统一映射到同一布尔值，并保持行为可预测

## 验证

完成后验证：

1. `workshop/image_post/run.py` 默认运行时传给 `run_single(..., publish=...)` 的值为 `False`
2. `workshop/image_post/run.py --publish` 时传给 `run_single(..., publish=...)` 的值为 `True`
3. `workshop/image_post/run.ps1` 默认不透传发布参数
4. `workshop/image_post/run.ps1 -Publish` 时透传 `--publish`
5. 未修改 `XHSImagePostPipeline` 及其内部发布逻辑

## 非目标

- 不修改 `workshop/mixed/run.py`
- 不修改 `src/agents/image_post` 内部实现
- 不自动运行发布流程
- 不改动飞书消息内容格式
