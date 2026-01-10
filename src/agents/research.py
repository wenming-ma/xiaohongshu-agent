"""
研究 Agent
使用 Playwright MCP Server 搜索和分析小红书内容

验证流程：
1. generator.run() 执行研究
2. ResearchDepthValidator 验证帖子数量（基于 MCP 工具调用追踪）
3. ResearchReviewValidator 验证数据质量
4. 两个都通过 → 返回结果
5. 任一失败 → 注入反馈，继续循环（保持消息历史）
"""
import json
import logfire
from datetime import datetime
from pathlib import Path
from dataclasses import replace
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.messages import (
    ModelRequest, UserPromptPart, ToolReturnPart, ModelResponse,
    TextPart, ToolCallPart, ThinkingPart
)
from typing import Any
from ..models.schemas import ResearchResult
from ..utils.model_factory import get_model
from ..utils.retry_handler import with_retry
from ..utils.navigate_tracker import NavigateTracker
from ..utils.logger import get_logger
from ..validators import ResearchDepthValidator, ResearchReviewValidator
from ..config.settings import RetryConfig, ResearchConfig, PathConfig, TimeoutConfig
from prompts import get_system_prompt, get_user_prompt

logger = get_logger(__name__)


class ResearchAgent:
    """
    小红书研究 Agent

    研究流程：
    1. 使用 Playwright MCP 工具在小红书搜索和浏览
    2. 进入高热帖子详情页，阅读内容和评论区
    3. 提取实体、案例等数据
    4. 验证帖子数量和数据质量
    5. 未通过则继续探索，直到满足要求
    """

    def __init__(self):
        """初始化研究 Agent"""
        # 获取带 HTTP 重试的 Model（根据配置选择 Anthropic 或 OpenRouter）
        model = get_model()

        # Playwright MCP Server 实例
        # 注意：使用 @latest 避免 npx 缓存导致的版本问题
        self.mcp_server = MCPServerStdio(
            command='npx',
            args=['-y', '@playwright/mcp@latest'],
            env={
                'HEADLESS': 'false',  # 显示浏览器窗口
                'BROWSER_TYPE': 'chromium',
                'USER_DATA_DIR': PathConfig.BROWSER_SESSION_XHS
            },
            tool_prefix='playwright',
            cache_tools=True,
            max_retries=RetryConfig.MCP_RETRIES,
            timeout=TimeoutConfig.MCP_INIT_TIMEOUT,
        )

        # 导航追踪器 - 包装 MCP Server 以追踪帖子详情页访问
        self.navigate_tracker = NavigateTracker(self.mcp_server)

        # 研究生成 Agent（使用追踪器包装的工具集）
        self.generator = Agent(
            model=model,
            output_type=ResearchResult,
            toolsets=[self.navigate_tracker],
            instrument=True,
            retries=RetryConfig.AGENT_RETRIES,
            system_prompt=(get_system_prompt("research"),),
        )

        # 初始化验证器
        self.depth_validator = ResearchDepthValidator(
            min_posts=ResearchConfig.MIN_POSTS_RESEARCHED
        )
        self.review_validator = ResearchReviewValidator(
            min_posts=ResearchConfig.MIN_POSTS_RESEARCHED
        )

        # 验证配置
        self.max_iterations = ResearchConfig.VALIDATION_MAX_RETRIES

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
                    if hasattr(tool, 'description') and tool.description:
                        logger.debug(f"    {tool.description[:80]}...")
        except Exception as e:
            logger.warning(f"无法列出工具: {e}")
            logger.info("工具将在首次 Agent 调用时自动发现")

    @with_retry(max_retries=RetryConfig.MAX_RETRIES, initial_delay=RetryConfig.INITIAL_DELAY)
    async def _run_generator(self, prompt, message_history):
        """对单次模型调用做重试，保持当前消息历史不丢失"""
        if prompt is None:
            return await self.generator.run(message_history=message_history)
        return await self.generator.run(prompt, message_history=message_history)

    async def research(
        self,
        topic: str,
        target_audience: str,
        output_dir: Path | None = None
    ) -> ResearchResult:
        """
        执行研究任务

        验证流程（内部循环）：
        1. generator.run() 执行研究
        2. ResearchDepthValidator 验证帖子数量
        3. ResearchReviewValidator 验证数据质量
        4. 两个都通过 → 返回结果
        5. 任一失败 → 注入反馈，继续循环

        @with_retry 处理网络/API 错误（重试整个研究）
        浏览器在验证通过后才关闭。

        Args:
            topic: 研究主题
            target_audience: 目标受众
            output_dir: 输出目录（用于保存中间结果）

        Returns:
            ResearchResult: 研究结果（已通过验证）
        """
        # 设置输出目录
        self._output_dir = output_dir
        # 历史迭代结果（用于合并）
        self._iteration_results: list[ResearchResult] = []
        # 最近一次"进度快照"文本，避免重复注入
        self._last_progress_snapshot: str | None = None
        
        # 准备初始提示词
        initial_prompt = get_user_prompt(
            "research",
            topic=topic,
            target_audience=target_audience,
            min_posts=ResearchConfig.MIN_POSTS_RESEARCHED
        )

        # 保持消息历史
        message_history = []
        result = None

        # 重置导航追踪器（强制清空，避免自动 reset 跳过）
        self.navigate_tracker.reset(force=True)

        logger.info(f"开始研究：{topic}")
        logger.info(f"目标受众：{target_audience}")
        logger.info(f"最大迭代次数：{self.max_iterations}")

        # 使用 logfire span 追踪整个研究过程
        with logfire.span(
            'research:workflow',
            topic=topic,
            target_audience=target_audience,
            max_iterations=self.max_iterations
        ) as research_span:
            async with self.mcp_server:  # 浏览器保持打开
                for iteration in range(self.max_iterations):
                    logger.info("=" * 50)
                    logger.info(f"第 {iteration + 1}/{self.max_iterations} 轮研究")
                    logger.info("=" * 50)

                    # 使用 logfire span 追踪每次迭代
                    with logfire.span(
                        'research:iteration',
                        iteration=iteration + 1,
                        max_iterations=self.max_iterations
                    ) as iteration_span:
                        # 1. 执行研究
                        if iteration == 0:
                            # 首轮：使用初始提示词；失败重试仅作用于本轮调用
                            agent_result = await self._run_generator(
                                initial_prompt,
                                message_history=message_history
                            )
                        else:
                            # 后续轮：继续沿用消息历史；失败重试不清空历史
                            agent_result = await self._run_generator(
                                None,
                                message_history=message_history
                            )

                        result = agent_result.output

                        # 更新消息历史
                        message_history = list(agent_result.all_messages())

                        # 获取追踪的帖子数量（真实数据）
                        tracked_stats = self.navigate_tracker.get_stats()
                        tracked_post_count = tracked_stats["post_detail_count"]

                        logger.info("本轮研究结果：")
                        logger.info(f"  - 帖子数量（追踪）: {tracked_post_count}")
                        logger.info(f"  - 帖子数量（自报）: {result.posts_researched}")
                        logger.info(f"  - 关键信息数量: {len(result.key_infos)}")
                        logger.info(f"  - 案例数量: {len(result.cases)}")
                        logger.info(f"  - 评论区数据占比: {result.comment_data_ratio:.0%}")

                        # 记录迭代结果到 span
                        iteration_span.set_attribute('tracked_post_count', tracked_post_count)
                        iteration_span.set_attribute('reported_post_count', result.posts_researched)
                        iteration_span.set_attribute('key_infos_count', len(result.key_infos))
                        iteration_span.set_attribute('cases_count', len(result.cases))
                        iteration_span.set_attribute('comment_data_ratio', result.comment_data_ratio)

                        # 构建验证上下文（包含追踪数据）
                        validation_context = {
                            "topic": topic,
                            "target_audience": target_audience,
                            "tracked_post_count": tracked_post_count,
                            "tracked_urls": tracked_stats["post_detail_urls"],
                        }

                        # 2. 验证帖子数量（使用追踪数据）
                        logger.info("验证研究深度...")
                        with logfire.span('research:validate_depth'):
                            depth_result = await self.depth_validator.validate(
                                result, validation_context
                            )

                        # 3. 验证数据质量
                        logger.info("验证数据质量...")
                        with logfire.span('research:validate_quality'):
                            review_result = await self.review_validator.validate(
                                result, validation_context
                            )

                        # 记录验证结果
                        iteration_span.set_attribute('depth_passed', depth_result.passed)
                        iteration_span.set_attribute('depth_score', depth_result.score)
                        iteration_span.set_attribute('review_passed', review_result.passed)
                        iteration_span.set_attribute('review_score', review_result.score)

                        # 4. 两个都通过？
                        if depth_result.passed and review_result.passed:
                            logger.info("研究验证全部通过！")
                            logger.info(f"  - 深度验证评分: {depth_result.score:.1f}/100")
                            logger.info(f"  - 质量验证评分: {review_result.score:.1f}/100")
                            
                            # 记录最终结果到研究 span
                            research_span.set_attribute('final_iteration', iteration + 1)
                            research_span.set_attribute('final_depth_score', depth_result.score)
                            research_span.set_attribute('final_review_score', review_result.score)
                            research_span.set_attribute('success', True)
                            
                            logfire.info(
                                'Research completed successfully',
                                topic=topic,
                                iterations=iteration + 1,
                                depth_score=depth_result.score,
                                review_score=review_result.score
                            )
                            # 保存并合并所有迭代结果
                            return self._finalize_result(
                                result, topic, iteration + 1, tracked_stats
                            )

                        # 5. 构建反馈，继续循环
                        feedback = self._combine_feedback(depth_result, review_result)
                        logger.warning("验证未通过，注入反馈继续探索...")

                        # 保存本轮研究结果到 JSON 文件，并记录到历史
                        saved_file = self._save_iteration_result(
                            result, topic, iteration + 1, tracked_stats
                        )
                        self._iteration_results.append(result)
                        logger.info(f"本轮数据已保存至: {saved_file}")

                        # 简化消息历史（替换工具调用结果为简短说明）
                        message_history = self._simplify_message_history(
                            message_history, saved_file
                        )

                        # 注入"截至目前累计成果"的进度快照，帮助下一轮基于已有数据继续补齐
                        progress_snapshot = self._build_progress_snapshot(
                            topic=topic,
                            tracked_stats=tracked_stats,
                            saved_file=saved_file,
                        )
                        if progress_snapshot and progress_snapshot != self._last_progress_snapshot:
                            message_history.append(
                                ModelRequest(parts=[UserPromptPart(content=progress_snapshot)])
                            )
                            self._last_progress_snapshot = progress_snapshot

                        # 注入反馈到消息历史
                        feedback_message = ModelRequest(
                            parts=[UserPromptPart(content=feedback)]
                        )
                        message_history.append(feedback_message)

                # 达到最大迭代次数
                logger.warning(f"达到最大迭代次数 ({self.max_iterations})，返回当前结果")
                
                # 记录超时结果
                research_span.set_attribute('final_iteration', self.max_iterations)
                research_span.set_attribute('success', False)
                research_span.set_attribute('reason', 'max_iterations_reached')
                
                logfire.warn(
                    'Research reached max iterations',
                    topic=topic,
                    max_iterations=self.max_iterations
                )
                # 保存并合并所有迭代结果
                return self._finalize_result(
                    result, topic, self.max_iterations, tracked_stats
                )

    def _finalize_result(
        self,
        current_result: ResearchResult,
        topic: str,
        iteration: int,
        tracked_stats: dict
    ) -> ResearchResult:
        """
        保存当前轮次结果并合并所有历史数据

        Args:
            current_result: 当前轮次的研究结果
            topic: 研究主题
            iteration: 当前迭代次数
            tracked_stats: 追踪统计信息

        Returns:
            合并后的研究结果
        """
        # 1. 保存当前轮次结果到 JSON
        saved_file = self._save_iteration_result(
            current_result, topic, iteration, tracked_stats
        )
        logger.info(f"本轮数据已保存至: {saved_file}")

        # 2. 如果没有历史数据，直接返回当前结果
        if not self._iteration_results:
            return current_result

        # 3. 合并所有历史结果 + 当前结果
        all_results = self._iteration_results + [current_result]
        
        # 合并列表字段（去重）
        merged_key_infos = []
        merged_cases = []
        merged_keywords = set()
        merged_post_sources = []
        seen_key_infos = set()
        seen_cases = set()
        seen_sources = set()

        for res in all_results:
            # 合并 key_infos（按内容去重）
            for info in res.key_infos:
                info_key = json.dumps(info, sort_keys=True, ensure_ascii=False)
                if info_key not in seen_key_infos:
                    seen_key_infos.add(info_key)
                    merged_key_infos.append(info)
            
            # 合并 cases（按内容去重）
            for case in res.cases:
                case_key = json.dumps(case, sort_keys=True, ensure_ascii=False)
                if case_key not in seen_cases:
                    seen_cases.add(case_key)
                    merged_cases.append(case)
            
            # 合并 keywords
            merged_keywords.update(res.keywords)
            
            # 合并 post_sources（按 URL 去重）
            for source in res.post_sources:
                source_url = source.get("url", json.dumps(source, sort_keys=True))
                if source_url not in seen_sources:
                    seen_sources.add(source_url)
                    merged_post_sources.append(source)

        # 4. 拼接所有 summary
        merged_summary = "\n\n---\n\n".join(
            f"【第{i+1}轮研究】\n{res.summary}"
            for i, res in enumerate(all_results)
            if res.summary
        )

        # 5. 计算 credibility 平均值
        credibility_map = {"low": 1, "medium": 2, "high": 3}
        credibility_reverse = {1: "low", 2: "medium", 3: "high"}
        credibility_scores = [
            credibility_map.get(res.credibility, 2)
            for res in all_results
        ]
        avg_credibility = round(sum(credibility_scores) / len(credibility_scores))
        merged_credibility = credibility_reverse.get(avg_credibility, "medium")

        # 6. 构建合并后的结果
        merged_result = ResearchResult(
            summary=merged_summary,
            key_infos=merged_key_infos,
            cases=merged_cases,
            keywords=list(merged_keywords),
            credibility=merged_credibility,
            data_points=len(merged_key_infos) + len(merged_cases),
            posts_researched=tracked_stats.get("post_detail_count", 0),
            post_sources=merged_post_sources,
            comment_data_ratio=current_result.comment_data_ratio
        )

        logger.info("合并历史数据：")
        logger.info(f"  - 关键信息: {len(merged_key_infos)} 条（来自 {len(all_results)} 轮）")
        logger.info(f"  - 案例: {len(merged_cases)} 个")
        logger.info(f"  - 关键词: {len(merged_keywords)} 个")
        logger.info(f"  - 帖子来源: {len(merged_post_sources)} 个")

        return merged_result

    def _build_progress_snapshot(
        self,
        *,
        topic: str,
        tracked_stats: dict[str, Any],
        saved_file: str,
        max_items: int = 10,
    ) -> str:
        """
        构建"截至目前已收集内容"的短摘要，注入到下一轮对话里，避免模型重复劳动。

        目标：信息密度高、长度可控（尽量 < ~2000 chars）。
        """
        if not self._iteration_results:
            return ""

        # 合并（去重）——尽量用轻量逻辑，避免引入额外依赖
        seen_key_infos: set[str] = set()
        seen_cases: set[str] = set()
        seen_keywords: set[str] = set()

        merged_key_infos: list[dict[str, Any]] = []
        merged_cases: list[dict[str, Any]] = []

        for res in self._iteration_results:
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

        # 选取展示（控制长度）
        def _short(obj: Any, limit: int = 120) -> str:
            s = str(obj)
            return s if len(s) <= limit else s[: limit - 12] + "...[truncated]"

        key_infos_preview = "\n".join(
            f"- {_short(item)}" for item in merged_key_infos[:max_items]
        ) or "- (none)"
        cases_preview = "\n".join(
            f"- {_short(item)}" for item in merged_cases[:max_items]
        ) or "- (none)"
        keywords_preview = ", ".join(list(seen_keywords)[: max_items]) or "(none)"

        tracked_urls = tracked_stats.get("post_detail_urls") or []
        if isinstance(tracked_urls, list):
            tracked_urls_preview = "\n".join(f"- {u}" for u in tracked_urls[-max_items:]) or "- (none)"
        else:
            tracked_urls_preview = f"- {_short(tracked_urls)}"

        return (
            f"【进度快照｜仅供参考，请勿在输出中重复】\n"
            f"- topic: {topic}\n"
            f"- tracked_post_count: {tracked_stats.get('post_detail_count', 0)}\n"
            f"- saved_json: {saved_file}\n\n"
            f"已保存的关键信息（示例，最多{max_items}条）：\n"
            f"{key_infos_preview}\n\n"
            f"已保存的案例（示例，最多{max_items}条）：\n"
            f"{cases_preview}\n\n"
            f"已保存的关键词（示例，最多{max_items}个）： {keywords_preview}\n\n"
            f"已进入的帖子详情页（最近{max_items}个）：\n"
            f"{tracked_urls_preview}\n\n"
            f"⚠️ 重要提醒：\n"
            f"- 以上历史数据已自动保存到文件，系统会自动合并所有轮次\n"
            f"- 本轮你只需输出【新收集】的数据，不要重复输出历史数据\n"
            f"- 请继续探索新帖子，收集新的关键信息和案例"
        )

    def _save_iteration_result(
        self,
        result,
        topic: str,
        iteration: int,
        tracked_stats: dict
    ) -> str:
        """
        保存本轮研究结果到 JSON 文件

        Args:
            result: 研究结果
            topic: 研究主题
            iteration: 当前迭代次数
            tracked_stats: 追踪统计信息

        Returns:
            保存的文件路径
        """
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"research_{timestamp}.json"
        
        # 保存到指定的输出目录（如 posts/当前工作区/）
        if self._output_dir:
            output_dir = self._output_dir
        else:
            # 回退到默认 output 目录
            output_dir = Path("output")
        output_dir.mkdir(parents=True, exist_ok=True)
        filepath = output_dir / filename

        # 构建保存数据
        data = {
            "topic": topic,
            "iteration": iteration,
            "timestamp": timestamp,
            "tracked_stats": tracked_stats,
            "result": result.model_dump() if hasattr(result, "model_dump") else str(result)
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return str(filepath)

    def _simplify_message_history(
        self,
        message_history: list,
        saved_file: str
    ) -> list:
        """
        简化消息历史，大幅减少 token 消耗

        优化策略：
        1. ToolReturnPart: 前3行 + [简化说明] + 后3行（最后一个保留完整）
        2. ToolCallPart: 简化大型参数（最后一个保留完整）
        3. TextPart: 截断超长内容（>500字符）
        4. ThinkingPart: 历史省略，仅保留最新一次
        5. 其他: 保留原样

        Args:
            message_history: 原始消息历史
            saved_file: 保存的文件路径

        Returns:
            简化后的消息历史
        """
        summary_text = f"[saved to {saved_file}, truncated]"

        # 1. 找出最后一个 ToolReturnPart / ToolCallPart / ThinkingPart 的位置
        last_tool_return_pos = None  # (msg_idx, part_idx)
        last_tool_call_pos = None    # (msg_idx, part_idx)
        last_thinking_pos = None     # (msg_idx, part_idx)

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

        # 2. 遍历并简化（保留最后一个工具调用/返回的完整内容）
        simplified = []

        for msg_idx, msg in enumerate(message_history):
            if isinstance(msg, ModelRequest):
                new_parts = []
                for part_idx, part in enumerate(msg.parts):
                    if isinstance(part, ToolReturnPart):
                        # 检查是否是最后一个 ToolReturnPart
                        is_last = (msg_idx, part_idx) == last_tool_return_pos
                        if is_last:
                            # 保留完整内容
                            new_parts.append(part)
                        else:
                            # 简化：前3行 + 说明 + 后3行
                            simplified_content = self._truncate_content(
                                part.content, summary_text
                            )
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
                        # 历史思考过程省略，只保留最新一次（用于理解当前上下文）
                        is_last = (msg_idx, part_idx) == last_thinking_pos
                        if is_last:
                            new_parts.append(part)
                        continue
                    if isinstance(part, ToolCallPart):
                        # 检查是否是最后一个 ToolCallPart
                        is_last = (msg_idx, part_idx) == last_tool_call_pos
                        if is_last:
                            # 保留完整参数
                            new_parts.append(part)
                        else:
                            # 简化工具调用参数
                            simplified_args = self._simplify_tool_args(part.args)
                            new_parts.append(ToolCallPart(
                                tool_name=part.tool_name,
                                tool_call_id=part.tool_call_id,
                                args=simplified_args
                            ))
                    elif isinstance(part, TextPart):
                        # 截断超长的模型文本响应
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
        """
        简化工具调用参数（移除大型数据如 HTML snapshot）

        Args:
            args: 工具参数（字典或 JSON 字符串）

        Returns:
            简化后的参数
        """
        if isinstance(args, str):
            # JSON 字符串，尝试解析
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                # 无法解析，直接截断
                if len(args) > 200:
                    return args[:150] + "...[truncated]..."
                return args

        if isinstance(args, dict):
            simplified = {}
            for key, value in args.items():
                if isinstance(value, str) and len(value) > 200:
                    # 截断长字符串
                    simplified[key] = value[:100] + f"...[{len(value)} chars truncated]..."
                else:
                    simplified[key] = value
            return simplified
        
        return args

    def _truncate_content(self, content: any, summary_text: str) -> str:
        """
        截断内容：保留前3行有效内容 + 简化说明 + 后3行有效内容

        Args:
            content: 原始内容（可能是字符串、字典或其他类型）
            summary_text: 简化说明文本

        Returns:
            截断后的字符串
        """
        # 转换为字符串
        if content is None:
            return summary_text
        if isinstance(content, dict):
            text = json.dumps(content, ensure_ascii=False, indent=2)
        else:
            text = str(content)

        # 过滤空行，只保留有实际内容的行
        all_lines = text.split('\n')
        non_empty_lines = [line for line in all_lines if line.strip()]

        # 如果有效行数较少，无需截断
        if len(non_empty_lines) <= 8:
            return text

        # 取前3行和后3行有效内容
        head_lines = non_empty_lines[:3]
        tail_lines = non_empty_lines[-3:]

        # 避免首尾重叠（当内容很短时）
        if len(non_empty_lines) <= 6:
            return '\n'.join(non_empty_lines)

        head = '\n'.join(head_lines)
        tail = '\n'.join(tail_lines)

        return f"{head}\n\n{summary_text}\n\n{tail}"

    def _combine_feedback(self, depth_result, review_result) -> str:
        """合并两个验证器的反馈"""
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
