"""
研究 Agent - ML 模型风格
使用 Playwright MCP Server 搜索和分析小红书内容

使用方式：
    agent = ResearchAgent()
    result = await agent.forward(topic, target_audience, output_dir)

验证流程：
1. forward() 执行研究
2. _step() 单次迭代生成
3. _validate() 验证帖子数量和数据质量
4. 通过 → 返回结果
5. 失败 → 注入反馈，继续循环
"""
import json
import logfire
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, replace
from typing import Any
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.messages import (
    ModelRequest, UserPromptPart, ToolReturnPart, ModelResponse,
    TextPart, ToolCallPart, ThinkingPart
)
from ...models.schemas import ResearchResult
from ...utils.minimax_provider import get_minimax_model
from ...utils.retry_handler import with_retry
from ...utils.navigate_tracker import NavigateTracker
from ...utils.logger import get_logger
from ...config.settings import RetryConfig, ResearchConfig, PathConfig, TimeoutConfig
from ...infra.login_agent import LoginAgent
from .depth_validator import ResearchDepthValidator
from .review_validator import ResearchReviewValidator
from .image_reader import ImageReaderAgent
from .web_search import WebSearchAgent
from .prompts import research_system_prompt, research_user_prompt

logger = get_logger(__name__)


# ============================================================================
# State 数据类：封装运行时状态
# ============================================================================

@dataclass
class ResearchState:
    """研究运行时状态（类似 hidden state）"""
    topic: str
    target_audience: str
    output_dir: Path | None

    # 消息历史
    message_history: list = field(default_factory=list)

    # 迭代结果
    iteration_results: list[ResearchResult] = field(default_factory=list)
    saved_files: list[str] = field(default_factory=list)

    # 追踪状态
    last_progress_snapshot: str | None = None
    tracked_stats: dict = field(default_factory=dict)

    # 当前结果
    current_result: ResearchResult | None = None


# ============================================================================
# ResearchAgent：ML 模型风格的研究 Agent
# ============================================================================

class ResearchAgent:
    """
    小红书研究 Agent（ML 模型风格）

    类似 PyTorch nn.Module 的设计：
    - __init__: 初始化所有组件
    - forward: 主执行入口
    - _step: 单次迭代
    - _validate: 验证逻辑

    使用方式：
        agent = ResearchAgent()
        result = await agent.forward(topic, target_audience)
    """

    # ========================================================================
    # 初始化
    # ========================================================================

    def __init__(self):
        """初始化研究 Agent"""
        self._init_mcp_server()
        self._init_tools()
        self._init_generator()
        self._init_validators()

    def _init_mcp_server(self):
        """初始化 Playwright MCP Server"""
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=['-y', '@playwright/mcp@latest', '--output-dir', str(PathConfig.DOWNLOADS_DIR)],
            env={
                'HEADLESS': 'false',
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': PathConfig.BROWSER_SESSION_XHS
            },
            tool_prefix='playwright',
            cache_tools=True,
            max_retries=RetryConfig.MCP_RETRIES,
            timeout=TimeoutConfig.MCP_INIT_TIMEOUT,
        )
        # 导航追踪器
        self.navigate_tracker = NavigateTracker(self.mcp_server)

    def _init_tools(self):
        """初始化工具集"""
        # LoginAgent - 处理登录/注册
        self.login_agent = LoginAgent(mcp_server=self.mcp_server)
        # 读图工具
        self.image_reader_agent = ImageReaderAgent()
        # Web 搜索工具
        self.web_search_agent = WebSearchAgent()

    def _init_generator(self):
        """初始化研究生成 Agent"""
        model = get_minimax_model()

        function_tools = [
            self.login_agent.get_tool(),
            self.image_reader_agent.get_tool(),
        ]

        self.generator = Agent(
            model=model,
            output_type=ResearchResult,
            toolsets=[self.navigate_tracker],
            tools=function_tools,
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(research_system_prompt(),),
        )

    def _init_validators(self):
        """初始化验证器"""
        self.depth_validator = ResearchDepthValidator(
            min_posts=ResearchConfig.MIN_POSTS_RESEARCHED
        )
        self.review_validator = ResearchReviewValidator(
            min_posts=ResearchConfig.MIN_POSTS_RESEARCHED
        )
        self.max_iterations = ResearchConfig.VALIDATION_MAX_RETRIES

    # ========================================================================
    # 主入口：forward
    # ========================================================================

    async def forward(
        self,
        topic: str,
        target_audience: str,
        output_dir: Path | None = None
    ) -> ResearchResult:
        """
        执行研究任务（主入口）

        类似 PyTorch 的 forward 方法，这是唯一的公开执行入口。

        Args:
            topic: 研究主题
            target_audience: 目标受众
            output_dir: 输出目录

        Returns:
            ResearchResult: 研究结果
        """
        # 1. 初始化状态
        state = self._init_state(topic, target_audience, output_dir)

        logger.info(f"开始研究：{topic}")
        logger.info(f"目标受众：{target_audience}")
        logger.info(f"最大迭代次数：{self.max_iterations}")

        # 2. 使用 logfire span 追踪整个研究过程
        with logfire.span(
            'research:workflow',
            topic=topic,
            target_audience=target_audience,
            max_iterations=self.max_iterations
        ) as research_span:

            # 3. 在 MCP 上下文中执行研究循环
            async with self.mcp_server:
                for iteration in range(self.max_iterations):
                    # 单次迭代
                    with logfire.span('research:iteration', iteration=iteration + 1):
                        # Step: 执行研究
                        await self._step(state, iteration)

                        # Validate: 验证结果
                        passed, depth_result, review_result = await self._validate(state)

                        if passed:
                            # 验证通过，记录并返回
                            self._log_success(research_span, iteration, depth_result, review_result, topic)
                            return self._finalize(state, iteration + 1)

                        # 验证失败，更新状态继续
                        self._update_state_on_failure(state, iteration, depth_result, review_result, topic)

                # 达到最大迭代次数
                self._log_max_iterations(research_span, topic)
                return self._finalize(state, self.max_iterations)

    # ========================================================================
    # 核心执行方法
    # ========================================================================

    def _init_state(
        self,
        topic: str,
        target_audience: str,
        output_dir: Path | None
    ) -> ResearchState:
        """初始化研究状态"""
        # 重置导航追踪器
        self.navigate_tracker.reset(force=True)

        return ResearchState(
            topic=topic,
            target_audience=target_audience,
            output_dir=output_dir
        )

    @with_retry(max_retries=RetryConfig.MAX_RETRIES, initial_delay=RetryConfig.INITIAL_DELAY)
    async def _run_generator(self, prompt, message_history):
        """对单次模型调用做重试"""
        if prompt is None:
            return await self.generator.run(message_history=message_history)
        return await self.generator.run(prompt, message_history=message_history)

    async def _step(self, state: ResearchState, iteration: int) -> None:
        """
        单次研究迭代

        Args:
            state: 研究状态
            iteration: 当前迭代序号（从 0 开始）
        """
        logger.info("=" * 50)
        logger.info(f"第 {iteration + 1}/{self.max_iterations} 轮研究")
        logger.info("=" * 50)

        # 构建提示词
        if iteration == 0:
            prompt = research_user_prompt(
                topic=state.topic,
                target_audience=state.target_audience,
                min_posts=ResearchConfig.MIN_POSTS_RESEARCHED,
            )
        else:
            prompt = None  # 后续轮次使用消息历史

        # 执行生成
        agent_result = await self._run_generator(prompt, state.message_history)

        # 更新状态
        state.current_result = agent_result.output
        state.message_history = list(agent_result.all_messages())
        state.tracked_stats = self.navigate_tracker.get_stats()

        # 日志
        self._log_step_result(state)

    async def _validate(self, state: ResearchState) -> tuple[bool, Any, Any]:
        """
        验证研究结果

        Returns:
            (passed, depth_result, review_result)
        """
        result = state.current_result
        tracked_stats = state.tracked_stats

        # 构建验证上下文
        validation_context = {
            "topic": state.topic,
            "target_audience": state.target_audience,
            "tracked_post_count": tracked_stats["post_detail_count"],
            "tracked_urls": tracked_stats["post_detail_urls"],
        }

        # 深度验证
        logger.info("验证研究深度...")
        with logfire.span('research:validate_depth'):
            depth_result = await self.depth_validator.validate(result, validation_context)

        # 质量验证
        logger.info("验证数据质量...")
        with logfire.span('research:validate_quality'):
            review_result = await self.review_validator.validate(result, validation_context)

        passed = depth_result.passed and review_result.passed
        return passed, depth_result, review_result

    def _finalize(self, state: ResearchState, iteration: int) -> ResearchResult:
        """
        最终化结果：保存并合并所有迭代数据

        Args:
            state: 研究状态
            iteration: 完成时的迭代次数

        Returns:
            合并后的研究结果
        """
        result = state.current_result

        # 保存当前轮次
        saved_file = self._save_iteration_result(
            result, state.topic, iteration, state.tracked_stats, state.output_dir, state.saved_files
        )
        logger.info(f"本轮数据已保存至: {saved_file}")

        # 如果没有历史，直接返回
        if not state.iteration_results:
            return result

        # 合并所有历史 + 当前
        return self._merge_results(state.iteration_results + [result], state.tracked_stats)

    # ========================================================================
    # 状态更新方法
    # ========================================================================

    def _update_state_on_failure(
        self,
        state: ResearchState,
        iteration: int,
        depth_result,
        review_result,
        topic: str
    ) -> None:
        """验证失败时更新状态"""
        logger.warning("验证未通过，注入反馈继续探索...")

        # 保存本轮结果
        saved_file = self._save_iteration_result(
            state.current_result, topic, iteration + 1,
            state.tracked_stats, state.output_dir, state.saved_files
        )
        state.iteration_results.append(state.current_result)
        logger.info(f"本轮数据已保存至: {saved_file}")

        # 简化消息历史
        state.message_history = self._simplify_message_history(state.message_history)

        # 注入进度快照
        progress_snapshot = self._build_progress_snapshot(state, saved_file)
        if progress_snapshot and progress_snapshot != state.last_progress_snapshot:
            state.message_history.append(
                ModelRequest(parts=[UserPromptPart(content=progress_snapshot)])
            )
            state.last_progress_snapshot = progress_snapshot

        # 注入反馈
        feedback = self._combine_feedback(depth_result, review_result)
        state.message_history.append(
            ModelRequest(parts=[UserPromptPart(content=feedback)])
        )

    # ========================================================================
    # 日志方法
    # ========================================================================

    def _log_step_result(self, state: ResearchState) -> None:
        """记录单步结果"""
        result = state.current_result
        tracked_count = state.tracked_stats["post_detail_count"]

        logger.info("本轮研究结果：")
        logger.info(f"  - 帖子数量（追踪）: {tracked_count}")
        logger.info(f"  - 帖子数量（自报）: {result.posts_researched}")
        logger.info(f"  - 关键信息数量: {len(result.key_infos)}")
        logger.info(f"  - 案例数量: {len(result.cases)}")
        logger.info(f"  - 评论区数据占比: {result.comment_data_ratio:.0%}")

    def _log_success(self, span, iteration: int, depth_result, review_result, topic: str) -> None:
        """记录成功日志"""
        logger.info("研究验证全部通过！")
        logger.info(f"  - 深度验证评分: {depth_result.score:.1f}/100")
        logger.info(f"  - 质量验证评分: {review_result.score:.1f}/100")

        span.set_attribute('final_iteration', iteration + 1)
        span.set_attribute('final_depth_score', depth_result.score)
        span.set_attribute('final_review_score', review_result.score)
        span.set_attribute('success', True)

        logfire.info(
            'Research completed successfully',
            topic=topic,
            iterations=iteration + 1,
            depth_score=depth_result.score,
            review_score=review_result.score
        )

    def _log_max_iterations(self, span, topic: str) -> None:
        """记录达到最大迭代次数"""
        logger.warning(f"达到最大迭代次数 ({self.max_iterations})，返回当前结果")

        span.set_attribute('final_iteration', self.max_iterations)
        span.set_attribute('success', False)
        span.set_attribute('reason', 'max_iterations_reached')

        logfire.warn(
            'Research reached max iterations',
            topic=topic,
            max_iterations=self.max_iterations
        )

    # ========================================================================
    # 工具方法
    # ========================================================================

    async def list_tools(self) -> None:
        """列出所有可用的 MCP 工具（用于验证）"""
        logger.info("正在检查可用工具...")
        try:
            async with self.mcp_server as server:
                tools = await server.list_tools()
                logger.info(f"发现 {len(tools)} 个 Playwright MCP 工具:")
                for tool in tools:
                    tool_name = f"{self.mcp_server.tool_prefix}_{tool.name}" if self.mcp_server.tool_prefix else tool.name
                    logger.debug(f"  - {tool_name}")
        except Exception as e:
            logger.warning(f"无法列出工具: {e}")

    # ========================================================================
    # 结果处理方法
    # ========================================================================

    def _merge_results(
        self,
        all_results: list[ResearchResult],
        tracked_stats: dict
    ) -> ResearchResult:
        """合并多轮研究结果"""
        merged_key_infos = []
        merged_cases = []
        merged_keywords = set()
        merged_post_sources = []
        seen_key_infos = set()
        seen_cases = set()
        seen_sources = set()

        for res in all_results:
            # 合并 key_infos
            for info in res.key_infos:
                info_key = json.dumps(info, sort_keys=True, ensure_ascii=False)
                if info_key not in seen_key_infos:
                    seen_key_infos.add(info_key)
                    merged_key_infos.append(info)

            # 合并 cases
            for case in res.cases:
                case_key = json.dumps(case, sort_keys=True, ensure_ascii=False)
                if case_key not in seen_cases:
                    seen_cases.add(case_key)
                    merged_cases.append(case)

            # 合并 keywords
            merged_keywords.update(res.keywords)

            # 合并 post_sources
            for source in res.post_sources:
                source_url = source.get("url", json.dumps(source, sort_keys=True))
                if source_url not in seen_sources:
                    seen_sources.add(source_url)
                    merged_post_sources.append(source)

        # 拼接 summary
        merged_summary = "\n\n---\n\n".join(
            f"【第{i+1}轮研究】\n{res.summary}"
            for i, res in enumerate(all_results)
            if res.summary
        )

        # 计算 credibility 平均值
        credibility_map = {"low": 1, "medium": 2, "high": 3}
        credibility_reverse = {1: "low", 2: "medium", 3: "high"}
        credibility_scores = [credibility_map.get(res.credibility, 2) for res in all_results]
        avg_credibility = round(sum(credibility_scores) / len(credibility_scores))
        merged_credibility = credibility_reverse.get(avg_credibility, "medium")

        merged_result = ResearchResult(
            summary=merged_summary,
            key_infos=merged_key_infos,
            cases=merged_cases,
            keywords=list(merged_keywords),
            credibility=merged_credibility,
            data_points=len(merged_key_infos) + len(merged_cases),
            posts_researched=tracked_stats.get("post_detail_count", 0),
            post_sources=merged_post_sources,
            comment_data_ratio=all_results[-1].comment_data_ratio
        )

        logger.info("合并历史数据：")
        logger.info(f"  - 关键信息: {len(merged_key_infos)} 条（来自 {len(all_results)} 轮）")
        logger.info(f"  - 案例: {len(merged_cases)} 个")
        logger.info(f"  - 关键词: {len(merged_keywords)} 个")
        logger.info(f"  - 帖子来源: {len(merged_post_sources)} 个")

        return merged_result

    def _save_iteration_result(
        self,
        result: ResearchResult,
        topic: str,
        iteration: int,
        tracked_stats: dict,
        output_dir: Path | None,
        saved_files: list[str]
    ) -> str:
        """保存本轮研究结果到 JSON 文件"""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"research_{timestamp}.json"

        if output_dir:
            out_dir = output_dir
        else:
            out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        filepath = out_dir / filename

        data = {
            "topic": topic,
            "iteration": iteration,
            "timestamp": timestamp,
            "tracked_stats": tracked_stats,
            "result": result.model_dump() if hasattr(result, "model_dump") else str(result)
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        saved_files.append(str(filepath))
        return str(filepath)

    # ========================================================================
    # 消息历史处理
    # ========================================================================

    def _build_progress_snapshot(self, state: ResearchState, saved_file: str, max_items: int = 10) -> str:
        """构建进度快照"""
        if not state.iteration_results:
            return ""

        # 合并去重
        seen_key_infos: set[str] = set()
        seen_cases: set[str] = set()
        seen_keywords: set[str] = set()
        merged_key_infos: list[dict] = []
        merged_cases: list[dict] = []

        for res in state.iteration_results:
            for info in res.key_infos:
                key = json.dumps(info, sort_keys=True, ensure_ascii=False)
                if key not in seen_key_infos:
                    seen_key_infos.add(key)
                    merged_key_infos.append(info)
            for case in res.cases:
                key = json.dumps(case, sort_keys=True, ensure_ascii=False)
                if key not in seen_cases:
                    seen_cases.add(key)
                    merged_cases.append(case)
            for kw in res.keywords:
                if kw:
                    seen_keywords.add(str(kw))

        def _short(obj: Any, limit: int = 120) -> str:
            s = str(obj)
            return s if len(s) <= limit else s[:limit - 12] + "...[truncated]"

        key_infos_preview = "\n".join(f"- {_short(item)}" for item in merged_key_infos[:max_items]) or "- (none)"
        cases_preview = "\n".join(f"- {_short(item)}" for item in merged_cases[:max_items]) or "- (none)"
        keywords_preview = ", ".join(sorted(seen_keywords)) or "(none)"

        tracked_urls = state.tracked_stats.get("post_detail_urls") or []
        tracked_urls_preview = "\n".join(f"- {u}" for u in tracked_urls[-max_items:]) if tracked_urls else "- (none)"

        saved_files = state.saved_files[:]
        if saved_file and saved_file not in saved_files:
            saved_files.append(saved_file)

        if len(saved_files) > max_items:
            saved_files_preview = "\n".join(f"- {p}" for p in saved_files[-max_items:])
            saved_files_note = f"(total {len(saved_files)} files, showing last {max_items})"
        else:
            saved_files_preview = "\n".join(f"- {p}" for p in saved_files) or "- (none)"
            saved_files_note = ""

        return (
            f"【进度快照｜仅供参考，请勿在输出中重复】\n"
            f"- topic: {state.topic}\n"
            f"- tracked_post_count: {state.tracked_stats.get('post_detail_count', 0)}\n"
            f"- saved_json:\n{saved_files_preview}\n"
            f"{(saved_files_note + chr(10)) if saved_files_note else ''}\n"
            f"已保存的关键信息（示例，最多{max_items}条）：\n{key_infos_preview}\n\n"
            f"已保存的案例（示例，最多{max_items}条）：\n{cases_preview}\n\n"
            f"已保存的关键词： {keywords_preview}\n\n"
            f"已进入的帖子详情页（最近{max_items}个）：\n{tracked_urls_preview}\n\n"
            f"⚠️ 重要提醒：\n"
            f"- 以上历史数据已自动保存到文件，系统会自动合并所有轮次\n"
            f"- 本轮你只需输出【新收集】的数据，不要重复输出历史数据\n"
            f"- 请继续探索新帖子，收集新的关键信息和案例"
        )

    def _simplify_message_history(self, message_history: list) -> list:
        """简化消息历史，减少 token 消耗"""
        summary_text = "... truncated ..."

        # 找最后位置
        last_tool_return_pos = None
        last_tool_call_pos = None
        last_thinking_pos = None

        for msg_idx, msg in enumerate(message_history):
            if isinstance(msg, ModelRequest):
                for part_idx, part in enumerate(msg.parts):
                    if isinstance(part, ToolReturnPart):
                        last_tool_return_pos = (msg_idx, part_idx)
            elif isinstance(msg, ModelResponse):
                for part_idx, part in enumerate(msg.parts):
                    if isinstance(part, ToolCallPart):
                        last_tool_call_pos = (msg_idx, part_idx)
                    elif isinstance(part, ThinkingPart):
                        last_thinking_pos = (msg_idx, part_idx)

        # 遍历简化
        simplified = []
        for msg_idx, msg in enumerate(message_history):
            if isinstance(msg, ModelRequest):
                new_parts = []
                for part_idx, part in enumerate(msg.parts):
                    if isinstance(part, ToolReturnPart):
                        is_last = (msg_idx, part_idx) == last_tool_return_pos
                        if is_last:
                            new_parts.append(part)
                        else:
                            simplified_content = self._truncate_content(part.content, summary_text)
                            new_parts.append(ToolReturnPart(
                                tool_name=part.tool_name,
                                tool_call_id=part.tool_call_id,
                                content=simplified_content,
                                timestamp=part.timestamp
                            ))
                    else:
                        new_parts.append(part)
                simplified.append(replace(msg, parts=new_parts))

            elif isinstance(msg, ModelResponse):
                new_parts = []
                for part_idx, part in enumerate(msg.parts):
                    if isinstance(part, ThinkingPart):
                        is_last = (msg_idx, part_idx) == last_thinking_pos
                        if is_last:
                            new_parts.append(part)
                        continue
                    if isinstance(part, ToolCallPart):
                        is_last = (msg_idx, part_idx) == last_tool_call_pos
                        if is_last:
                            new_parts.append(part)
                        else:
                            simplified_args = self._simplify_tool_args(part.args)
                            new_parts.append(ToolCallPart(
                                tool_name=part.tool_name,
                                tool_call_id=part.tool_call_id,
                                args=simplified_args
                            ))
                    elif isinstance(part, TextPart):
                        if len(part.content) > 500:
                            truncated = part.content[:400] + "\n...[truncated]..."
                            new_parts.append(TextPart(content=truncated))
                        else:
                            new_parts.append(part)
                    else:
                        new_parts.append(part)

                if new_parts:
                    simplified.append(replace(msg, parts=new_parts))
            else:
                simplified.append(msg)

        return simplified

    def _simplify_tool_args(self, args: dict | str) -> dict | str:
        """简化工具调用参数"""
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                if len(args) > 200:
                    return args[:150] + "...[truncated]..."
                return args

        if isinstance(args, dict):
            simplified = {}
            for key, value in args.items():
                if isinstance(value, str) and len(value) > 200:
                    simplified[key] = value[:100] + f"...[{len(value)} chars truncated]..."
                else:
                    simplified[key] = value
            return simplified

        return args

    def _truncate_content(self, content: Any, summary_text: str) -> str:
        """截断内容：保留前3行 + 说明 + 后3行"""
        if content is None:
            return summary_text
        if isinstance(content, dict):
            text = json.dumps(content, ensure_ascii=False, indent=2)
        else:
            text = str(content)

        all_lines = text.split('\n')
        non_empty_lines = [line for line in all_lines if line.strip()]

        if len(non_empty_lines) <= 8:
            return text

        head_lines = non_empty_lines[:3]
        tail_lines = non_empty_lines[-3:]

        if len(non_empty_lines) <= 6:
            return '\n'.join(non_empty_lines)

        return f"{chr(10).join(head_lines)}\n\n{summary_text}\n\n{chr(10).join(tail_lines)}"

    def _combine_feedback(self, depth_result, review_result) -> str:
        """合并验证器反馈"""
        feedbacks = []
        if not depth_result.passed and depth_result.feedback:
            feedbacks.append(depth_result.feedback)
        if not review_result.passed and review_result.feedback:
            feedbacks.append(review_result.feedback)

        combined = "\n\n---\n\n".join(feedbacks)

        return (
            f"**验证未通过，请继续探索**\n\n"
            f"{combined}\n\n"
            f"**重要提醒**：\n"
            f"- 上一轮收集的数据已自动保存，系统会自动合并所有轮次结果\n"
            f"- 本轮你只需输出【本轮新收集】的关键信息和案例\n"
            f"- 不要在输出中重复之前轮次已收集的内容\n\n"
            f"**请基于已搜索的内容发散思维，尝试不同关键词组合和细分角度，进入更多帖子详情页收集【新的】数据。**"
        )
