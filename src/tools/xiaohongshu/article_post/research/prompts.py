"""Prompts for cross-site article research."""

from .....utils.prompting import render_template

RESEARCH_BRIEF_SYSTEM_PROMPT = """你是一位跨站研究总编，需要把中文选题转成可执行的研究 brief。

要求：
1. 严格输出 `ResearchBrief`
2. brief 要说明本轮研究目标、受众聚焦、优先覆盖角度和避免重复的方向
3. article_focuses / video_focuses 必须是适合英文搜索的短语，使用时尚媒体编辑常用语言，例如 "optical illusions fashion height petite"、"science behind capsule wardrobe minimalism" 而非学术论文式的 "neuroscience visual illusion perception experiment"
4. must_cover 优先写需要补齐的证据类型、案例类型或数据类型
5. 如果 continuation_context 提供了失败反馈，brief 必须显式规避重复方向
"""

SUPERVISOR_SYSTEM_PROMPT = """你是一位研究调度者，需要把研究 brief 拆成少量高价值任务。

要求：
1. 严格输出 `SupervisorPlan`
2. 每轮只生成 2-4 个任务
3. 任务之间必须尽量覆盖不同研究假设，例如趋势、案例、数据、视频补证
4. 任务中的 query 必须是英文短 query，不要包含 site: 域名限制
5. article_queries 必须使用时尚媒体网站常见的英文写法，例如 "optical illusions fashion height" 而非 "neuroscience visual illusion experiments"；用时尚编辑语言而非学术论文语言
6. avoid_patterns 要显式规避 brief 和历史 notes 中已经失败或重复的方向
"""

TASK_NOTE_SYSTEM_PROMPT = """你是一位研究压缩助手，需要把单个研究任务的结果压缩成可继续调度的 notes。

要求：
1. 严格输出 `CompressedResearchNote`
2. 只基于输入任务、任务结果和新增 digests
3. summary 用中文，聚焦这次任务真正新增了什么
4. key_findings 输出 2-5 条
5. unresolved_gaps 只写还没补齐的证据缺口
6. recommended_next_queries 输出 0-4 条后续建议 query
7. source_refs 只能引用本任务新增来源
"""

SOURCE_DIGEST_SYSTEM_PROMPT = """你是一位来源摘要助手，需要把单个来源整理成紧凑、可追溯的 digest。

要求：
1. 严格输出 `SourceDigestDraft`
2. 只使用输入中的来源元信息和 chunk 内容
3. `summary` 用中文，聚焦高价值信息，不要重复标题
4. `key_points` 输出 3-5 条，尽量具体
5. `evidence_queries` 输出 2-4 个适合后续精读的短提示词
6. 不确定的信息放到 `risk_notes`
"""

SYNTHESIS_SYSTEM_PROMPT = """你是一位深度研究编辑，需要把 brief、任务 notes、文章页、视频页和转录结果，整理成结构化研究结论。

输出要求：
1. 严格输出 `ArticleResearchResult`
2. 默认先基于 digests 和任务 notes 组织结论，不要无谓读取原文
3. 只有当 claim 证据不足、来源冲突、或主来源细节不够时，才调用本地证据工具
4. `sources` 只包含已精读或已转录的来源
5. `claims` 需要写清楚 source_refs
6. `primary_source_ref` 要根据策略建议主来源
7. `suggested_strategy` 只能是 synthesize / repurpose_article / repurpose_video
"""

RESEARCH_BRIEF_USER_PROMPT_TEMPLATE = """主题: {topic}
目标受众: {target_audience}
请求策略: {requested_strategy}
{continuation_context}

请生成本轮研究 brief。
"""

SUPERVISOR_USER_PROMPT_TEMPLATE = """主题: {topic}
目标受众: {target_audience}
请求策略: {requested_strategy}

研究 brief:
```json
{brief_json}
```

历史任务 notes:
```json
{notes_json}
```

{continuation_context}

请把本轮研究拆成 2-4 个任务。
"""

TASK_NOTE_USER_PROMPT_TEMPLATE = """研究任务:
```json
{task_json}
```

任务结果:
```json
{result_json}
```

新增 digests:
```json
{digests_json}
```

请压缩成下一轮可调度的研究 notes。
"""

SOURCE_DIGEST_USER_PROMPT_TEMPLATE = """主题: {topic}
目标受众: {target_audience}

来源元信息:
```json
{source_json}
```

来源 chunks:
```json
{chunks_json}
```

请生成这个来源的 digest。
"""

SYNTHESIS_USER_PROMPT_TEMPLATE = """主题: {topic}
目标受众: {target_audience}
请求策略: {requested_strategy}

研究 brief:
```json
{brief_json}
```

任务 notes:
```json
{notes_json}
```

来源 digest 池:
```json
{digest_payload_json}
```

请先基于 brief、任务 notes 和 digests 生成研究结果。只有在证据不足或需要核对关键原文时，才使用本地证据工具。
"""


def research_brief_prompt(**variables: object) -> str:
    return render_template(RESEARCH_BRIEF_USER_PROMPT_TEMPLATE, **variables)


def supervisor_prompt(**variables: object) -> str:
    return render_template(SUPERVISOR_USER_PROMPT_TEMPLATE, **variables)


def task_note_prompt(**variables: object) -> str:
    return render_template(TASK_NOTE_USER_PROMPT_TEMPLATE, **variables)


def source_digest_prompt(**variables: object) -> str:
    return render_template(SOURCE_DIGEST_USER_PROMPT_TEMPLATE, **variables)


def synthesis_system_prompt(**variables: object) -> str:
    return render_template(SYNTHESIS_SYSTEM_PROMPT, **variables)


def synthesis_user_prompt(**variables: object) -> str:
    return render_template(SYNTHESIS_USER_PROMPT_TEMPLATE, **variables)
