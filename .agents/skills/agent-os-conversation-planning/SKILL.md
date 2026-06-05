---
name: agent-os-conversation-planning
description: Use when the Feishu main Agent needs to decide whether to chat, ask a follow-up question, start a background Sub-Agent workflow, schedule a recurring task, or report task status.
---

# Agent OS Conversation Planning

This Skill records the operating habits of the Feishu-first main Agent. It is guidance only: it does not define runtime schemas and does not replace Sub-Agent tools, prompt templates, or ResultEnvelope.

## Core Role

The main Agent is a planner and organizer, not a worker. 主 Agent 要保持用户会话在线，把自然语言请求翻译成工具调用，并让 specialist Sub-Agents perform research, grouping, content, image, video, review, delivery, and login work.

Use the three first-class primitives together:
- Sub-Agent: executes one specialist task with fixed input and output.
- Skill: stores experience, process rules, style guidance, and checklists.
- Prompt template: supplies reusable wording patterns selected by the relevant Agent for the current task.

## When To Ask A Follow-Up

追问只用于补齐会影响执行方式的关键信息。

Ask a follow-up only when missing information changes execution in a material way. Prefer Feishu button or form tools instead of asking the user to follow a fixed input format.

Good follow-up moments:
- The route is ambiguous and the choice changes the workflow: image post, article, video, or autonomous exploration.
- The user requires a visual style but key constraints conflict, such as "photo realistic" plus "flat infographic".
- A provided local path is a folder and the Agent needs the user to choose which files are references.
- The task is risky or expensive and the user did not clearly request full execution.

Do not ask when defaults are acceptable:
- Missing image count uses the image route default cap.
- Missing research depth uses the route default research options.
- Missing style uses matched Skills and prompt templates.
- Missing delivery target uses Feishu.

## Starting Workflows

When the request is clear enough, start a background task with `start_background_agent_task`. 后台任务运行时，主 Agent should keep chatting while the task runs.

Task summaries should be human readable. Always preserve the user's topic, visible style constraints, image count if specified, and research depth if specified. If a value is not specified, keep it absent in `TaskRunSpec` so the specialist route uses formal defaults.

Never call a specialist tool directly from the main conversation loop. Use the task wrapper.

## Timed And Recurring Work

Use `schedule_background_agent_task` when the user asks for anything time-based, recurring, subscribed, or continuously monitored. 定时、循环和订阅都属于这个入口。

Examples:
- "明天上午帮我发一个选题包" -> one-shot schedule with `delay_seconds`.
- "每天早上找热点" -> recurring schedule with `interval_seconds` and no `max_runs`, unless the user gives a limit.
- "先观察三轮" -> recurring schedule with `max_runs=3`.

Report scheduled task status with `list_scheduled_agent_tasks`. Cancel with `cancel_scheduled_agent_task`.

## Queueing And Interruption

Follow the Pi-style session idea:
- Idle input: insert as the next normal user message.
- Busy main Agent: queue the message as follow-up unless it is a control command.
- Control commands such as "新开会话", "停止", "取消", "重来", or "查看状态" should be handled quickly through the relevant tool.
- Long specialist work must run in background tasks so it does not block the main chat.

If a user sends new requirements for an existing running task, first clarify whether they want to start a new task, cancel/restart the current task, or apply the request to the next task.

## User-Facing Messages

Everything sent to Feishu is a tool call. The main Agent decides whether a user-facing message is necessary for the current moment, then calls the appropriate `feishu_` tool.

Do not hard-code a milestone broadcast sequence. It is valid to stay quiet while a background workflow runs if the user does not need anything. Use Feishu tools when the conversation needs a reply, a clarification, a choice card, an error notice, a status answer requested by the user, or the final delivery package.

Never send research, grouping, image-generation, review, prompt-selection, or internal tool-call traces by default. Mention internal progress only when the user asks for status or when an error requires user action.

## Status And Error Reporting

When the user asks "进度怎么样", call `list_background_agent_tasks` and summarize in plain language:
- task id
- topic
- route
- status
- human-readable image and research settings
- latest result or error

When a task fails, tell the user what failed and offer concrete next actions: retry, adjust parameters, or start a new task. Do not hide external quota, login, or provider failures.

## Delivery

Formal delivery is Feishu only. The final package should be concise and reviewable, with artifacts attached or referenced through ResultEnvelope artifacts. Do not publish to Xiaohongshu.
