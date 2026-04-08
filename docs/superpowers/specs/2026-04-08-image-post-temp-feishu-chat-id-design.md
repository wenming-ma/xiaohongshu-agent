# workshop/image_post 临时 Feishu Chat ID 覆盖设计

- 日期：2026-04-08
- 范围：`workshop/image_post/run.py`、`workshop/image_post/run.ps1`
- 相关：`src/utils/feishu_notifier.py`

## 目标

为 `workshop/image_post` 的本次 batch 执行增加一个“临时飞书 chat_id 覆盖”能力，使操作员可以把本批次消息发送到指定飞书群聊 `oc_34e4d2807836899d83d87c71a4db439f`，同时不修改 `.env` 或其他持久化环境变量配置。

## 当前行为

- `FeishuNotifier` 初始化时从 `FeishuConfig.CHAT_ID` 读取默认群聊 ID，见 `src/utils/feishu_notifier.py:79`
- `send_message(...)`、`send_image(...)` 等接口支持可选 `chat_id` 参数；如果不传，则回退到 notifier 当前默认 `self.chat_id`
- `workshop/image_post/run.py` 当前调用 `get_feishu_notifier()` 后发送消息时未传入 `chat_id`
- 因此当前 `image_post` batch 只能使用环境变量中的默认飞书群 ID

## 方案对比

### 方案 A：入口参数显式透传覆盖（采用）

在 `workshop/image_post` 的 Python 与 PowerShell 入口增加临时参数：
- Python: `--feishu-chat-id`
- PowerShell: `-FeishuChatId`

runner 在本次执行过程中将该值显式传给所有飞书发送调用。

优点：
- 作用域清晰，仅限当前 batch
- 不修改环境变量，不依赖隐式状态
- 命令行上可见、可审计
- 不影响其他 workshop 脚本

缺点：
- 需要同步修改两个入口文件和少量发送调用

### 方案 B：运行时修改 notifier 单例的 `chat_id`

runner 启动后拿到 `get_feishu_notifier()` 返回的单例对象并改写其 `chat_id`。

优点：
- 改动少

缺点：
- 语义隐式
- 单例状态在当前进程内共享，不如参数透传清晰
- 后续更难判断某次消息到底是默认 chat 还是临时覆盖 chat

### 方案 C：临时进程环境变量注入

在 shell 包装层仅对当前进程注入 `FEISHU_CHAT_ID`。

优点：
- 不落盘

缺点：
- 仍然是“环境变量路径”，不如入口参数直观
- 用户已明确要求不要修改环境变量中的值，本设计避免采用这条路径

## 采用设计

采用方案 A。

### 1. Python 入口新增 `--feishu-chat-id`

在 `workshop/image_post/run.py` 中：
- 在 CLI 中新增 `--feishu-chat-id`
- 将该参数作为可选字符串向下传递到飞书发送相关逻辑
- 不传时保持现有行为，继续使用默认环境变量配置

### 2. 仅覆盖本 batch 的飞书发送目标

本次覆盖只影响 `workshop/image_post/run.py` 中发生的飞书发送调用，包括：
- 发布成功通知
- 封面图发送
- Feishu review 模式下的完整内容发送
- review 模式下的图片发送

实现方式采用“显式传参”，而不是修改 notifier 全局默认状态。

### 3. PowerShell 入口新增 `-FeishuChatId`

在 `workshop/image_post/run.ps1` 中：
- 新增 `-FeishuChatId` 参数
- 仅当传入该值时，向 Python 入口追加 `--feishu-chat-id <value>`
- 不传时不追加任何参数

### 4. 本次批量使用方式

本次目标群聊 ID 为：

`oc_34e4d2807836899d83d87c71a4db439f`

因此本次运行可以使用：

```bash
uv run python workshop/image_post/run.py --feishu-chat-id oc_34e4d2807836899d83d87c71a4db439f
```

或：

```powershell
./workshop/image_post/run.ps1 -FeishuChatId oc_34e4d2807836899d83d87c71a4db439f
```

如果还要真实发布到小红书，则与已有发布参数组合：

```bash
uv run python workshop/image_post/run.py --publish --feishu-chat-id oc_34e4d2807836899d83d87c71a4db439f
```

## 兼容性与边界

- 不修改 `src/utils/feishu_notifier.py` 的默认配置来源
- 不修改 `.env`
- 不影响 `workshop/mixed`、`workshop/article_post`、`workshop/styled_image_post` 等其他 runner
- 不改变飞书消息内容格式，仅改变本次 batch 的目标群 ID

## 风险与规避

1. **部分飞书发送调用遗漏**
   - 规避：统一检查 `run.py` 中所有 `send_message(...)` 与 `send_image(...)` 调用点并全部透传
2. **PowerShell 与 Python 入口行为不一致**
   - 规避：同步增加参数并做一一映射
3. **空字符串覆盖默认 chat_id**
   - 规避：仅在参数值非空时传递；空值视为未设置

## 验证

完成后验证：

1. `workshop/image_post/run.py` CLI 中存在 `--feishu-chat-id`
2. `workshop/image_post/run.ps1` 参数中存在 `-FeishuChatId`
3. `run.ps1` 仅在提供 `-FeishuChatId` 时透传 `--feishu-chat-id`
4. `run.py` 中所有本 runner 触发的飞书发送调用都能接收并使用该覆盖值
5. 未修改 `FeishuConfig.CHAT_ID` 的读取逻辑
6. 未修改任何环境变量文件

## 非目标

- 不改造全仓库所有飞书调用点
- 不新增全局配置项
- 不把临时 chat id 写回配置文件或环境变量
