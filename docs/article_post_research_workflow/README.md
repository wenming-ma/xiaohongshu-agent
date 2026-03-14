# Article Post Research Workflow

## 目标

这份文档说明 `src/tools/xiaohongshu/article_post/research/` 当前的研究工作流。

这次重构的目标不是换掉现有抓取能力，而是把原先偏单体的 research loop 拆成明确的阶段：

1. `brief`
2. `supervisor planning`
3. `concurrent search`
4. `serial visit and collect`
5. `digest and task note compression`
6. `synthesis`
7. `validation and retry`

外部契约保持不变：

- `XHSArticlePostTool.execute()` 不改调用方式
- `ResearchAgent.forward()` 不改签名
- `ArticleResearchResult` 不改公共 schema
- `content` 和 `image` phase 继续消费完整的 research JSON

## 入口和核心文件

- Tool 入口: `src/tools/xiaohongshu/article_post/tool.py`
- Research Agent: `src/tools/xiaohongshu/article_post/research/agent.py`
- Research prompts: `src/tools/xiaohongshu/article_post/research/prompts.py`
- Research state: `src/tools/xiaohongshu/article_post/research/state.py`
- Search and evidence tools: `src/tools/xiaohongshu/article_post/research/tools.py`
- Iteration persistence: `src/tools/xiaohongshu/article_post/research/utils.py`
- Public schema: `src/tools/xiaohongshu/article_post/schemas.py`

## 设计原则

### 1. Hybrid query generation

query 不是纯程序写死，也不是让 agent 裸发最终搜索请求。

- Agent 负责决定研究方向:
  - 研究目标
  - 每轮 task
  - article query seed
  - video query seed
  - 哪些缺口需要继续补
- 程序负责决定执行方式:
  - `site:` 域名约束
  - query 去重
  - 搜索层并发
  - 候选结果归并
  - URL 去重
  - 页面访问顺序

### 2. Search 和 visit 强分离

search 阶段只拿候选元信息，不读取页面。

visit 阶段才允许：

- 调用 Playwright MCP 读取页面
- 判断 paywall
- 提取正文
- 判断是否是 video candidate
- 转录视频
- 生成 `CollectedSource`

### 3. 并发只到搜索层

当前只对 `DomainSearchClient.search()` 做并发。

页面访问和转录仍然串行，原因是：

- `ArticlePageReader` 依赖共享 Playwright MCP session
- 多页面并发导航会互相覆盖浏览器上下文
- 本轮先稳定 orchestration，再考虑 MCP 隔离后的全链路多 agent 并发

### 4. Synthesizer 默认基于 digests 和 notes 工作

synthesis 默认不需要反复读取原文。

默认输入是：

- `ResearchBrief`
- `CompressedResearchNote`
- `SourceDigest`
- source refs

只有在 claim 证据不足时，synthesizer 才会调用 evidence tools 读取受控摘录。

## 状态模型

`ResearchState` 现在包含两层状态。

### 业务主状态

- `topic`
- `target_audience`
- `strategy`
- `current_result`
- `collected_sources`
- `digests_by_source`
- `continuation_context`

### 编排状态

- `brief`
- `supervisor_iteration`
- `pending_tasks`
- `completed_task_results`
- `current_notes`
- `aggregated_notes`
- `current_task_candidates`
- `current_candidates`
- `current_collected`
- `current_digests`

这些内部状态不会扩散到公共 schema，但会被保存到 iteration snapshot 里，方便调试和续轮补证。

## 内部模型

### ResearchBrief

描述整轮研究的稳定目标，字段包括：

- `objective`
- `audience_focus`
- `article_focuses`
- `video_focuses`
- `must_cover`
- `avoid_patterns`
- `iteration_guidance`

作用：

- 替代旧实现里单次 query planner 对全流程的直接驱动
- 给 supervisor 提供一个高层但稳定的研究框架

### ResearchTask

表示 supervisor 派发的单个研究任务，字段包括：

- `task_id`
- `goal`
- `source_focus`
- `article_queries`
- `video_queries`
- `done_when`
- `avoid_patterns`

典型任务会按不同 hypothesis 拆开，例如：

- 趋势和主论点
- 编辑部案例
- 专家建议
- 视频补证

### ResearchTaskResult

表示一个 researcher unit 执行后的结构化结果，字段包括：

- `candidate_results`
- `collected_source_refs`
- `new_digests`
- `raw_findings`
- `gaps`
- `suggested_followups`

### CompressedResearchNote

表示 task 结果的压缩版本，供 supervisor 和 synthesizer 继续使用，字段包括：

- `summary`
- `key_findings`
- `unresolved_gaps`
- `recommended_next_queries`
- `source_refs`

它不承载整页原文，避免把长文本重新灌回上层调度。

## 端到端流程

### Step 1. 创建工作目录和初始状态

`ResearchAgent.forward()` 首先调用 `create_state(...)`。

职责：

- 创建 `ResearchState`
- 为这次 research 准备 `working_dir`
- 初始化 `seen_candidate_urls`
- 初始化 `seen_source_urls`

如果 tool 没有显式传入输出目录，会在 `posts/article/_tmp/...` 下创建临时目录。

### Step 2. 生成 ResearchBrief

`build_research_brief(state)` 调用 brief builder agent。

输入：

- `topic`
- `target_audience`
- `requested_strategy`
- `continuation_context`

输出：

- `ResearchBrief`

失败时会进入 fallback brief，确保后续流程不会因为 LLM 规划失败而直接中断。

### Step 3. 生成 SupervisorPlan

`run_supervisor_iteration(state, iteration)` 调用 supervisor agent。

输入：

- 当前 brief
- 最近几轮压缩 notes
- `continuation_context`

输出：

- `SupervisorPlan`
- 其中包含 2 到 4 个 `ResearchTask`

如果 supervisor 输出不完整，程序会补默认 task，保证每轮至少有可执行的研究方向。

### Step 4. 编译 task queries

`_compile_task_queries(task)` 会把 agent 给出的 seed query 编译成最终执行 query。

这里会做的事情：

- article query seed 和 video query seed 标准化
- 用 `build_site_queries(...)` 注入 `site:` 约束
- 根据 `source_focus` 决定 article 和 video query 的先后顺序
- 控制单个 task 的最大 query 数量

这一层是程序控制的，不允许 agent 直接控制底层搜索执行策略。

### Step 5. 搜索层并发

`_search_candidates(tasks, state)` 是第一层并发点。

执行逻辑：

1. 聚合所有 task 编译后的 queries
2. 对完全相同的 query 去重
3. 建立 `query -> task_ids` 映射
4. 用 `asyncio.Semaphore(3)` 并发调用 `DomainSearchClient.search()`
5. 按 URL 去重
6. 将结果回填为：
   - `state.current_candidates`
   - `state.current_task_candidates`

注意：

- 同一 URL 不会因为被多个 query 命中而重复进入全局候选集
- 但同一结果可以同时映射给多个 task

### Step 6. researcher unit 串行访问页面

`run_researcher_unit(state, task, candidates)` 逐个 task 执行。

这里不会并发跑多个 page visit。

内部会调用 `_visit_and_collect_sources(...)`，其职责包括：

- 串行访问候选页
- 过滤无效页面
- 过滤正文过短页面
- 过滤 login wall 且正文不足的页面
- 识别 video candidate
- 必要时调用 `GenericVideoTranscriber`
- 计算质量分
- 生成 `CollectedSource`

去重规则：

- `seen_candidate_urls` 阻止候选搜索结果重复进入
- `seen_source_urls` 阻止最终页面重复作为来源进入

### Step 7. 生成 digest

`_build_task_digests(state, sources)` 对本 task 新增来源逐个生成 digest。

步骤：

1. `SourceChunker` 对来源内容切块
2. `SourceDigestorAgent` 读取 source payload + chunks
3. 输出 `SourceDigest`
4. 写入 `state.digests_by_source`

这一层仍然按来源串行执行，主要是为了控制 LLM 调用和证据顺序。

### Step 8. 压缩 task note

`compress_task_result(task, task_result)` 把任务执行结果压缩成 `CompressedResearchNote`。

这里保留的信息是：

- 任务总结
- 关键发现
- 未解决缺口
- 下一步建议 query
- 相关 source refs

作用：

- 给下一轮 supervisor 参考
- 给 synthesizer 提供更短的研究上下文

### Step 9. 聚合 notes 并保存内部快照

每轮 task 执行完成后，agent 会：

- 把 `current_notes` 追加到 `aggregated_notes`
- 写出 `research_brief.json`
- 写出 `research_notes.json`
- 写出 `research_tasks_iter_XX.json`

这些文件主要用于：

- 调试
- 续轮失败排查
- 后续人工回放研究过程

### Step 10. 构建本地 evidence store

`synthesize_result(...)` 前会调用 `_build_local_evidence(...)`。

这一步会：

- 把所有 `CollectedSource` 落盘到 `research_sources/`
- 为每个 source 保存 chunks
- 保存 `digests.json`
- 保存 `source_index.json`

同时暴露四个本地 evidence tools 给 synthesizer：

- `list_saved_sources`
- `read_source_digest`
- `read_source_excerpt`
- `read_primary_source`

### Step 11. 生成 ArticleResearchResult

`synthesize_result(...)` 调用 synthesizer agent 生成最终 `ArticleResearchResult`。

输入内容包括：

- `brief`
- `aggregated_notes`
- `current_iteration_notes`
- task result 摘要
- 所有 digests
- source refs

之后程序还会做兼容性修正：

- 用 `collected_sources` 重建 `research.sources`
- 用已有转录重建 `research.transcripts`
- 缺省时补 `primary_source_ref`
- 如果用户请求了固定 strategy，则覆盖自动推荐策略
- 如果模型仍返回 `AUTO`，则回退到 `SYNTHESIZE`

### Step 12. 验证

`validate(output)` 会做硬规则校验。

当前关键门槛：

- 至少 `MIN_SOURCE_PAGES`
- 至少 `MIN_UNIQUE_DOMAINS`
- 必须有结构化 `claims`
- 每个 claim 必须有 `source_refs`
- 如果是 `REPURPOSE_VIDEO`，必须有成功的转录

### Step 13. 验证失败后的续轮

如果未通过验证，会调用 `on_validation_failed(...)`。

这一步会：

1. 保存当前 iteration snapshot
2. 生成 `continuation_context`
3. 在下一轮把失败反馈、已收集来源、digest refs、最近任务、缺口摘要重新喂给 brief 和 supervisor

这使得下一轮不是简单重跑，而是带着上下文继续补证。

### Step 14. 完成与落盘

验证通过后会调用 `finalize(...)`。

最终会保留：

- `research.json`
- `research_brief.json`
- `research_notes.json`
- `research_tasks_iter_XX.json`
- `research_iter_XX_*.json`
- `research_sources/*.json`
- `digests.json`
- `source_index.json`

## 并发边界

当前并发策略是有意保守的。

### 已并发的部分

- query search

具体方式：

- `asyncio.gather(...)`
- `asyncio.Semaphore(3)`

### 仍然串行的部分

- page visit
- video transcription
- source digest generation
- evidence save
- synthesizer final generation

### 为什么不并发 page visit

因为当前 `ArticlePageReader` 走共享 Playwright MCP，会有以下风险：

- 多个 task 同时导航时，页面上下文相互覆盖
- 提取结果可能串台
- 登录态和浏览器状态不可预测

所以现在的并发边界是：

- 搜索快一点
- 抓取稳一点

## 持久化产物说明

### `research_iter_XX_*.json`

这是轮次级快照，当前不仅保存旧字段，也保存新的 orchestration 数据：

- `brief`
- `supervisor_iteration`
- `pending_tasks`
- `completed_task_results`
- `current_notes`
- `aggregated_notes`
- `current_task_candidates`

### `research_brief.json`

记录本次研究的高层 brief。

### `research_notes.json`

记录累计 task 压缩 notes。

### `research_tasks_iter_XX.json`

记录每轮 supervisor 拆出的 tasks 和对应 task result。

### `research_sources/*.json`

记录每个 source 的原始受控 payload 和 chunk 数据。

### `digests.json`

记录最终所有 `SourceDigest`。

### `source_index.json`

记录 source ref 到文件路径的索引。

## 下游如何消费 research 结果

### Content phase

`content/agent.py` 继续消费完整 `ArticleResearchResult`。

它重点依赖：

- `summary`
- `claims`
- `sources`
- `transcripts`
- `suggested_strategy`
- `primary_source_ref`

### Image phase

`image/agent.py` 继续消费 `ArticleResearchResult` 和内容生成结果。

它主要利用：

- 标题
- lead
- section source refs
- prompt hints

因此这次重构没有碰公共 schema。

## 失败和降级路径

为了保证 workflow 稳定，很多阶段都有 fallback。

### brief 失败

- 使用默认 `ResearchBrief`

### supervisor 失败

- 使用默认 `ResearchTask`

### task note 压缩失败

- 用 task result 中的 findings 和 gaps 回填

### 某个页面读取失败

- 跳过，不中断全局流程

### 某个视频转录失败

- 该来源仍可作为 article source 保留，除非当前策略强依赖视频转录

## 未来扩展方向

当前工作流已经把接口边界准备好了，下一步可以沿这些方向扩展：

1. 多 Playwright session 隔离后，放开 researcher unit 并发
2. 增加 source credibility gating
3. 增加 provider abstraction
4. 增加搜索缓存和断点恢复
5. 增加 source curation 配置
6. 增加更细粒度的 task priority

## 一句话总结

现在的 `article_post` research phase 不是简单的爬虫 loop，而是一个以 LLM 做研究规划、以程序做执行约束、以本地 evidence store 做证据承载的分阶段研究流水线。
