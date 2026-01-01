"""
图片审核 Agent
验证生成图片的质量和小红书风格（独立 Agent）

所有提示词统一在 prompts/image.yaml 管理
"""
from pathlib import Path
from typing import List, Sequence, Union
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.messages import UserContent
from ..models.schemas import GeneratedImage, ImageReviewResult, ImageReviewIssue
from ..utils.anthropic_provider import get_anthropic_model
from prompts import get_system_prompt, get_user_prompt


class ImageReviewAgent:
    """小红书图片审核 Agent"""

    # 文件大小阈值（小于此值可能是损坏的图片）
    MIN_FILE_SIZE = 10 * 1024  # 10KB

    def __init__(self):
        """初始化图片审核 Agent"""
        # 获取带 HTTP 重试的 Model（max_retries=5）
        model = get_anthropic_model()

        # 视觉审核 Agent（多模态，可以读取图片）
        # 系统提示词从 prompts/image_review.yaml 读取
        self.visual_reviewer = Agent(
            model=model,
            output_type=ImageReviewResult,
            instrument=True,
            system_prompt=(get_system_prompt("image_review"),),
        )

    async def review(
        self,
        images: List[GeneratedImage],
        topic: str,
        expected_count: int = 3
    ) -> ImageReviewResult:
        """
        审核图片质量

        Args:
            images: 待审核的图片列表
            topic: 主题（用于判断相关性）
            expected_count: 期望的图片数量

        Returns:
            ImageReviewResult: 审核结果
        """
        print("   🔍 开始审核图片...")

        issues = []
        file_check = {}

        # 1. 文件检查（Python 代码执行）
        file_issues = self._check_files(images, expected_count)
        issues.extend(file_issues)

        # 更新 file_check 状态
        for img in images:
            path = Path(img.image_path)
            file_check[img.image_type] = path.exists()

        # 2. 视觉审核（只检查存在的图片）
        existing_images = [
            img for img in images
            if Path(img.image_path).exists() and Path(img.image_path).stat().st_size >= self.MIN_FILE_SIZE
        ]

        if existing_images:
            visual_result = await self._check_visual_style(existing_images, topic, expected_count, file_check)
            # 合并视觉审核发现的问题
            issues.extend(visual_result.issues)

        # 3. 计算最终评分
        score = self._calculate_score(issues)
        passed = score >= 60 and not any(i.severity == "critical" for i in issues)

        result = ImageReviewResult(
            passed=passed,
            score=score,
            issues=issues,
            summary=self._generate_summary(passed, score, issues),
            file_check=file_check
        )

        # 打印审核结果
        status = "✅ 通过" if passed else "❌ 未通过"
        print(f"   {status} (评分: {score:.1f})")

        return result

    def _check_files(
        self,
        images: List[GeneratedImage],
        expected_count: int
    ) -> List[ImageReviewIssue]:
        """
        文件检查（存在性、大小、数量）

        Args:
            images: 图片列表
            expected_count: 期望数量

        Returns:
            发现的问题列表
        """
        issues = []

        # 检查每个图片文件
        for img in images:
            path = Path(img.image_path)

            if not path.exists():
                issues.append(ImageReviewIssue(
                    type="file_missing",
                    severity="critical",
                    image_type=img.image_type,
                    description=f"{img.image_type} 图片文件不存在: {path}",
                    suggestion="重新生成并确保下载完成"
                ))
            elif path.stat().st_size < self.MIN_FILE_SIZE:
                issues.append(ImageReviewIssue(
                    type="file_too_small",
                    severity="critical",
                    image_type=img.image_type,
                    description=f"{img.image_type} 图片文件过小 ({path.stat().st_size} bytes)，可能损坏",
                    suggestion="重新生成图片"
                ))

        # 检查数量
        if len(images) < expected_count:
            issues.append(ImageReviewIssue(
                type="count_insufficient",
                severity="critical",
                image_type="all",
                description=f"图片数量不足，期望 {expected_count} 张，实际 {len(images)} 张",
                suggestion="补充生成缺失的图片"
            ))

        return issues

    async def _check_visual_style(
        self,
        images: List[GeneratedImage],
        topic: str,
        expected_count: int,
        file_check: dict
    ) -> ImageReviewResult:
        """
        使用 Claude 视觉能力检查图片风格

        Args:
            images: 存在的图片列表
            topic: 主题
            expected_count: 期望数量
            file_check: 文件检查结果

        Returns:
            ImageReviewResult: 视觉审核结果
        """
        # 构建文件检查结果描述
        file_check_desc = "\n".join([
            f"- {img_type}: {'✅ 存在' if exists else '❌ 缺失'}"
            for img_type, exists in file_check.items()
        ])

        # 从 prompts/image_review.yaml 加载并渲染 user prompt
        prompt_text = get_user_prompt(
            "image_review",
            topic=topic,
            expected_count=expected_count,
            file_check_result=file_check_desc
        )

        # 构建多模态消息：文本 + 图片
        user_content: List[UserContent] = [prompt_text]

        # 添加每张图片
        for img in images:
            path = Path(img.image_path)
            if path.exists():
                try:
                    # 使用 BinaryContent.from_path 读取本地图片
                    image_content = BinaryContent.from_path(path)
                    user_content.append(f"\n### {img.image_type} 图片：")
                    user_content.append(image_content)
                except Exception as e:
                    print(f"      ⚠️ 无法读取图片 {path}: {e}")

        # 调用多模态审核
        print(f"      🔍 视觉审核中（{len(images)} 张图片）...")
        try:
            result = await self.visual_reviewer.run(user_content)
            return result.output
        except Exception as e:
            print(f"      ⚠️ 视觉审核失败: {e}")
            # 视觉审核失败时返回默认通过（仅依赖文件检查）
            return ImageReviewResult(
                passed=True,
                score=80,
                issues=[],
                summary=f"视觉审核跳过（{e}）",
                file_check=file_check
            )

    def _calculate_score(self, issues: List[ImageReviewIssue]) -> float:
        """
        计算评分

        Args:
            issues: 问题列表

        Returns:
            评分 0-100
        """
        score = 100.0

        for issue in issues:
            if issue.severity == "critical":
                score -= 25
            elif issue.severity == "warning":
                score -= 10
            else:  # info
                score -= 5

        return max(0, score)

    def _generate_summary(
        self,
        passed: bool,
        score: float,
        issues: List[ImageReviewIssue]
    ) -> str:
        """
        生成审核总结

        Args:
            passed: 是否通过
            score: 评分
            issues: 问题列表

        Returns:
            审核总结字符串
        """
        if passed:
            return f"审核通过，评分 {score:.1f}"

        # 统计问题
        critical_count = sum(1 for i in issues if i.severity == "critical")
        warning_count = sum(1 for i in issues if i.severity == "warning")

        parts = [f"审核未通过，评分 {score:.1f}"]
        if critical_count > 0:
            parts.append(f"严重问题 {critical_count} 个")
        if warning_count > 0:
            parts.append(f"警告 {warning_count} 个")

        return "，".join(parts)

    def format_report(self, result: ImageReviewResult) -> str:
        """
        格式化审核报告

        Args:
            result: 审核结果

        Returns:
            格式化的报告字符串
        """
        lines = []

        # 标题
        status = "✅ 通过" if result.passed else "❌ 未通过"
        lines.append(f"图片审核结果: {status} (得分: {result.score:.1f}/100)")
        lines.append("")

        # 总结
        lines.append(f"📝 总结: {result.summary}")
        lines.append("")

        # 文件检查
        lines.append("📁 文件检查:")
        for img_type, exists in result.file_check.items():
            icon = "✅" if exists else "❌"
            lines.append(f"   - {img_type}: {icon}")
        lines.append("")

        # 问题列表
        if result.issues:
            lines.append("⚠️  发现的问题:")
            for i, issue in enumerate(result.issues, 1):
                severity_icon = {
                    "critical": "🔴",
                    "warning": "🟡",
                    "info": "🔵"
                }.get(issue.severity, "⚪")

                lines.append(f"   {i}. [{severity_icon} {issue.severity.upper()}] {issue.image_type}")
                lines.append(f"      问题: {issue.description}")
                lines.append(f"      建议: {issue.suggestion}")
                lines.append("")
        else:
            lines.append("✨ 未发现问题")

        return "\n".join(lines)

    def get_failed_image_types(self, result: ImageReviewResult) -> List[str]:
        """
        获取审核失败的图片类型列表（用于重新生成）

        Args:
            result: 审核结果

        Returns:
            失败的图片类型列表
        """
        failed_types = set()

        for issue in result.issues:
            if issue.severity == "critical" and issue.image_type != "all":
                failed_types.add(issue.image_type)

        return list(failed_types)
