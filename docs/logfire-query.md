# Logfire 查询 API 使用指南

本项目通过 [Pydantic Logfire](https://logfire.pydantic.dev) 自动记录 Agent 与 LLM 的每一轮交互。
通过 Query API 可以用 SQL 回溯完整对话流程，排查问题。

## 认证

查询 API 需要 **Read Token**（`.env` 中的 `LOGFIRE_READ_TOKEN`），在 [Logfire 后台](https://logfire-us.pydantic.dev) → Settings → Read tokens 中创建。

## 快速开始

```python
import os
from dotenv import load_dotenv
from logfire.query_client import LogfireQueryClient

load_dotenv()
READ_TOKEN = os.environ["LOGFIRE_READ_TOKEN"]

with LogfireQueryClient(read_token=READ_TOKEN) as client:
    result = client.query_json(
        sql="SELECT start_timestamp, message, duration FROM records ORDER BY start_timestamp DESC LIMIT 10"
    )
    for col in result["columns"]:
        print(f"{col['name']}: {col['values']}")
```

也可以直接 HTTP 调用：

```bash
curl -H "Authorization: Bearer $LOGFIRE_READ_TOKEN" \
  "https://logfire-us.pydantic.dev/v1/query?sql=SELECT+message+FROM+records+LIMIT+5"
```

> 默认只返回最近 24 小时数据，可通过 `min_timestamp` / `max_timestamp` 参数调整。行数默认 500，最大 10,000。

---

## Trace 数据结构

一次 Agent 运行会产生一棵 span 树，层级关系如下：

```
research:workflow                              ← 研究工作流（顶层）
  └─ research:iteration                        ← 一轮研究迭代
       └─ agent run                            ← pydantic-ai Agent 运行
            ├─ chat MiniMax-M2.5               ← 第 1 轮 LLM 调用 → finish: tool_call
            ├─ running tools                   ← 执行工具
            │    └─ running tool: browser_nav   ← 单个工具执行
            ├─ chat MiniMax-M2.5               ← 第 2 轮 LLM 调用 → finish: tool_call
            ├─ running tools
            │    └─ running tool: read_image
            ├─ chat MiniMax-M2.5               ← 第 N 轮 LLM 调用 → finish: stop（最终回复）
            ...
       └─ research:validate_depth              ← 深度验证
       └─ research:validate_quality            ← 质量验证（内嵌独立 agent run）
  └─ research:iteration                        ← 下一轮迭代...
```

每个 span 通过 `trace_id` 关联同一次请求，通过 `parent_span_id` / `span_id` 构建父子关系。

### 核心 span 类型

| span_name | 含义 |
|-----------|------|
| `chat <模型名>` | 一次 LLM API 调用（如 `chat MiniMax-M2.5`、`chat gemini-3-flash-preview`） |
| `running tools` | 批量工具执行（message 显示 `running N tool(s)`） |
| `running tool` | 单个工具执行（message 显示 `running tool: <工具名>`） |
| `agent run` | pydantic-ai Agent 完整运行（包含多轮 chat + tool） |
| `research:workflow` | 研究工作流顶层 |
| `research:iteration` | 研究单轮迭代 |
| `research:validate_depth` / `research:validate_quality` | 研究结果验证 |

---

## LLM 调用详情（`chat` span）

`chat` span 的 `attributes` 包含完整的 LLM 交互数据，通过 `->>'key'` 访问：

| 属性 | 说明 |
|------|------|
| `gen_ai.request.model` | 请求模型名（如 `MiniMax-M2.5`） |
| `gen_ai.response.model` | 实际响应模型名 |
| `gen_ai.input.messages` | 完整输入消息（含 system prompt、历史对话） |
| `gen_ai.output.messages` | LLM 输出（含 thinking、text、tool_call） |
| `gen_ai.response.finish_reasons` | 结束原因：`["stop"]`（最终回复）/ `["tool_call"]`（调用工具）/ `["length"]`（截断） |
| `gen_ai.usage.input_tokens` | 输入 token 数（含缓存） |
| `gen_ai.usage.output_tokens` | 输出 token 数 |
| `gen_ai.usage.details.cache_read_input_tokens` | 缓存命中的 input token 数 |
| `gen_ai.usage.details.thoughts_tokens` | 思考 token 数（部分模型支持） |
| `gen_ai.tool.definitions` | 本轮可用的工具定义列表 |
| `gen_ai.provider.name` | 提供商（`anthropic` 等） |
| `server.address` | API 地址（如 `api.minimaxi.com`） |

### 工具调用详情（`running tool` span）

| 属性 | 说明 |
|------|------|
| `gen_ai.tool.name` | 工具名（如 `playwright_browser_click`） |
| `gen_ai.tool.call.id` | 工具调用 ID |
| `tool_arguments` | 工具输入参数（JSON） |
| `tool_response` | 工具返回结果 |

工具执行失败时 `is_exception = true`，`exception_message` 包含错误信息。

### Agent 运行汇总（`agent run` span）

| 属性 | 说明 |
|------|------|
| `agent_name` / `gen_ai.agent.name` | Agent 名称 |
| `model_name` | 使用的模型 |
| `final_result` | Agent 最终输出结果（含 summary） |
| `pydantic_ai.all_messages` | **完整对话历史**（所有轮次的 messages） |
| `gen_ai.usage.input_tokens` | 整次运行的总 input token |
| `gen_ai.usage.output_tokens` | 整次运行的总 output token |
| `gen_ai.usage.details.cache_read_input_tokens` | 整次运行的总缓存 token |

---

## 常用查询

### 1. 追踪一次完整 Agent 交互过程

先找到 trace_id，然后展开整棵调用树：

```sql
-- 找最近的 agent run
SELECT trace_id, start_timestamp, message, duration, service_name
FROM records
WHERE span_name = 'agent run'
ORDER BY start_timestamp DESC
LIMIT 5
```

```sql
-- 展开某次 trace 的完整交互流程
SELECT
    start_timestamp,
    span_name,
    message,
    duration,
    is_exception,
    attributes->>'gen_ai.response.finish_reasons' AS finish_reason
FROM records
WHERE trace_id = '<your-trace-id>'
ORDER BY start_timestamp
```

### 2. 查看某次 LLM 调用的输入输出

```sql
SELECT
    start_timestamp,
    attributes->>'gen_ai.request.model' AS model,
    attributes->>'gen_ai.input.messages' AS input_messages,
    attributes->>'gen_ai.output.messages' AS output_messages,
    attributes->>'gen_ai.response.finish_reasons' AS finish_reason,
    duration
FROM records
WHERE trace_id = '<your-trace-id>' AND span_name LIKE 'chat %'
ORDER BY start_timestamp
```

### 3. 查看某次工具调用的参数和返回值

```sql
SELECT
    start_timestamp,
    message,
    attributes->>'gen_ai.tool.name' AS tool_name,
    attributes->>'tool_arguments' AS tool_args,
    attributes->>'tool_response' AS tool_response,
    is_exception,
    exception_message
FROM records
WHERE trace_id = '<your-trace-id>' AND span_name = 'running tool'
ORDER BY start_timestamp
```

### 4. 查看 Agent 最终输出和完整消息历史

```sql
SELECT
    start_timestamp,
    attributes->>'agent_name' AS agent,
    attributes->>'model_name' AS model,
    attributes->>'final_result' AS result,
    attributes->>'gen_ai.usage.input_tokens' AS total_input_tok,
    attributes->>'gen_ai.usage.output_tokens' AS total_output_tok,
    duration
FROM records
WHERE span_name = 'agent run'
ORDER BY start_timestamp DESC
LIMIT 10
```

### 5. 查看工具失败详情

```sql
SELECT
    start_timestamp,
    message,
    exception_type,
    exception_message,
    attributes->>'tool_arguments' AS tool_args,
    service_name
FROM records
WHERE span_name = 'running tool' AND is_exception = true
ORDER BY start_timestamp DESC
LIMIT 20
```

### 6. 各模型 token 用量统计

```sql
SELECT
    attributes->>'gen_ai.request.model' AS model,
    COUNT(*) AS calls,
    SUM(CAST(attributes->>'gen_ai.usage.input_tokens' AS INT)) AS total_input,
    SUM(CAST(attributes->>'gen_ai.usage.output_tokens' AS INT)) AS total_output,
    AVG(duration) AS avg_ms
FROM records
WHERE span_name LIKE 'chat %'
GROUP BY model
ORDER BY calls DESC
```

### 7. 慢 LLM 调用排查

```sql
SELECT
    start_timestamp,
    attributes->>'gen_ai.request.model' AS model,
    CAST(attributes->>'gen_ai.usage.input_tokens' AS INT) AS input_tok,
    CAST(attributes->>'gen_ai.usage.output_tokens' AS INT) AS output_tok,
    duration,
    trace_id
FROM records
WHERE span_name LIKE 'chat %' AND duration > 30000
ORDER BY duration DESC
LIMIT 20
```

### 8. 按服务筛选

```sql
-- 服务名: xiaohongshu-agent / xiaohongshu-agent-mixed-batch / xiaohongshu-agent-article-batch
SELECT start_timestamp, message, duration
FROM records
WHERE service_name = 'xiaohongshu-agent-mixed-batch'
  AND span_name = 'agent run'
ORDER BY start_timestamp DESC
LIMIT 20
```

### 9. 错误类型统计

```sql
SELECT exception_type, COUNT(*) AS cnt
FROM records
WHERE is_exception = true
GROUP BY exception_type
ORDER BY cnt DESC
```

---

## 其他

- **可用表**：`records`（主表）、`records_all`（不受时间窗口限制）、`metrics`、`ai_counts`、`annotations`
- **返回格式**：SDK 支持 `query_json` / `query_json_rows` / `query_csv` / `query_arrow`
- **Web UI**：https://logfire-us.pydantic.dev 可可视化浏览 traces
- **官方文档**：https://logfire.pydantic.dev/docs/how-to-guides/query-api/
