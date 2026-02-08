from typing import List
from pydantic_ai import Agent

from .....core.base_validator import InternalValidator, InternalValidationResult
from ..schemas import VideoSource, Platform
from .....utils.anthropic_provider import get_anthropic_model
from .....utils.logger import get_logger

logger = get_logger(__name__)

VIDEO_QUALITY_SYSTEM_PROMPT = """你是专业的视频内容质量评估专家，专注于识别高质量、有故事性的视频内容。

## 评估标准

### ✅ 高质量视频特征（应该保留）
1. **完整故事性**
   - 有明确的开头、发展、结尾
   - 讲述完整的经历或教程
   - 有清晰的主题和信息传递

2. **内容深度**
   - 提供实用信息或知识
   - 展示独特的视角或经验
   - 有教育价值或启发性

3. **制作质量**
   - 画面稳定清晰
   - 有剪辑和后期处理
   - 音频清晰可听

4. **时长合理**
   - 30秒-5分钟为佳
   - 内容充实，不拖沓

5. **原创性**
   - 原创内容或深度二创
   - 有个人观点和见解
   - 非简单搬运

### ❌ 低质量视频特征（应该过滤）
1. **随意拍摄**
   - 没有明确主题
   - 画面晃动模糊
   - 无剪辑的原始素材

2. **碎片化内容**
   - 纯娱乐搞笑片段（无深度）
   - 单纯的舞蹈/对口型视频
   - 随机的日常琐事

3. **营销导向**
   - 纯产品广告
   - 夸张的标题党
   - 诱导点击的低质内容

4. **技术问题**
   - 画质极差
   - 音频不清晰
   - 明显的侵权内容

5. **时长不当**
   - 过短（<20秒）信息量不足
   - 过长（>10分钟）不适合短视频平台

## 评分规则（总分100）

### 内容质量（40分）
- 故事完整性：0-15分
- 信息价值：0-15分
- 原创性：0-10分

### 制作质量（30分）
- 画面质量：0-10分
- 剪辑水平：0-10分
- 音频质量：0-10分

### 适配性（30分）
- 小红书受众匹配度：0-15分
- 时长合理性：0-10分
- 话题相关性：0-5分

## 通过标准
- **总分 >= 70**: 通过，推荐下载
- **总分 60-69**: 边缘，需要人工复核
- **总分 < 60**: 不通过，过滤掉

## 输出要求
基于视频的标题、描述、互动数据、时长等元信息，给出：
1. 各维度详细评分
2. 总分
3. 是否通过（passed）
4. 详细反馈（优点和问题）
"""

VIDEO_QUALITY_USER_PROMPT_TEMPLATE = """## 评估视频质量

**话题**: {topic}
**平台**: {platform}

**视频信息**:
- URL: {url}
- 标题: {title}
- 描述: {description}
- 作者: {author}
- 时长: {duration}秒
- 点赞: {likes}
- 评论: {comments}
- 分享: {shares}

## 评估任务

基于以上信息，从以下维度评估视频质量：

1. **内容质量**（40分）
   - 从标题和描述判断是否有完整故事
   - 是否提供有价值的信息
   - 是否具有原创性

2. **制作质量推测**（30分）
   - 从互动数据推测质量（高互动通常意味着好质量）
   - 从标题判断是否经过精心策划
   - 从作者信息判断是否专业

3. **小红书适配性**（30分）
   - 内容是否符合小红书用户兴趣
   - 时长是否合理（30秒-5分钟为佳）
   - 话题是否与"{topic}"相关

请严格评分，只有真正高质量的视频才应该通过！
"""


class VideoQualityValidator(InternalValidator):
    """视频质量深度验证器 - 在下载前评估视频质量"""

    def __init__(self, pass_score: float = 70.0):
        self.pass_score = pass_score
        self.quality_agent: Agent | None = None

    @property
    def validator_name(self) -> str:
        return "VideoQuality"

    def _init_agent(self):
        if self.quality_agent is None:
            model = get_anthropic_model()
            self.quality_agent = Agent(
                model=model,
                system_prompt=VIDEO_QUALITY_SYSTEM_PROMPT,
            )

    async def validate(self, video: VideoSource, context: dict) -> InternalValidationResult:
        self._init_agent()

        topic = context.get("topic", "未知")

        prompt = VIDEO_QUALITY_USER_PROMPT_TEMPLATE.format(
            topic=topic,
            platform=video.platform.value,
            url=video.url,
            title=video.title or "无标题",
            description=video.description or "无描述",
            author=video.author or "未知",
            duration=video.duration_seconds or 0,
            likes=video.engagement.likes,
            comments=video.engagement.comments,
            shares=video.engagement.shares,
        )

        try:
            result = await self.quality_agent.run(prompt)
            response_text = result.data

            score = self._extract_score(response_text)
            passed = score >= self.pass_score

            if passed:
                feedback = f"✅ 质量评分: {score}/100 - 通过"
            else:
                feedback = f"❌ 质量评分: {score}/100 - 未通过\n\n{response_text}"

            logger.info(f"视频质量评估: {video.title[:30]}... - 评分: {score}/100 - {'通过' if passed else '未通过'}")

            validation_result = InternalValidationResult(
                passed=passed,
                feedback=feedback,
                score=score,
            )
            self._log_result(validation_result)
            return validation_result

        except Exception as e:
            logger.error(f"视频质量评估失败: {e}")
            return InternalValidationResult(
                passed=False,
                feedback=f"质量评估失败: {str(e)}",
                score=0.0,
            )

    def _extract_score(self, text: str) -> float:
        import re

        score_patterns = [
            r"总分[：:]\s*(\d+)",
            r"得分[：:]\s*(\d+)",
            r"评分[：:]\s*(\d+)",
            r"(\d+)\s*分",
            r"(\d+)/100",
        ]

        for pattern in score_patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))

        lines = text.split("\n")
        for line in lines:
            if "总分" in line or "得分" in line or "评分" in line:
                numbers = re.findall(r"\d+", line)
                if numbers:
                    return float(numbers[0])

        logger.warning("未能从响应中提取评分，默认50分")
        return 50.0


class VideoListQualityFilter:
    """视频列表质量过滤器 - 批量评估并过滤低质量视频"""

    def __init__(self, pass_score: float = 70.0, min_quality_videos: int = 3):
        self.validator = VideoQualityValidator(pass_score=pass_score)
        self.min_quality_videos = min_quality_videos

    async def filter_videos(
        self,
        videos: List[VideoSource],
        topic: str,
        max_videos: int = 5,
    ) -> tuple[List[VideoSource], List[str]]:
        """
        过滤视频列表，只保留高质量视频

        Returns:
            (high_quality_videos, feedback_messages)
        """
        logger.info(f"开始质量评估: {len(videos)} 个视频")

        high_quality_videos = []
        low_quality_videos = []
        feedback_messages = []

        for i, video in enumerate(videos):
            logger.info(f"评估视频 [{i+1}/{len(videos)}]: {video.title[:50]}...")

            validation = await self.validator.validate(
                video,
                context={"topic": topic}
            )

            if validation.passed:
                high_quality_videos.append(video)
                logger.info(f"  ✅ 通过 - 评分: {validation.score}/100")
            else:
                low_quality_videos.append(video)
                logger.warning(f"  ❌ 未通过 - 评分: {validation.score}/100")
                feedback_messages.append(
                    f"过滤掉低质量视频: {video.title[:50]} (评分: {validation.score}/100)"
                )

            if len(high_quality_videos) >= max_videos:
                logger.info(f"已找到足够的高质量视频 ({max_videos} 个)，停止评估")
                break

        logger.info(f"质量过滤完成: {len(high_quality_videos)} 个通过，{len(low_quality_videos)} 个被过滤")

        return high_quality_videos, feedback_messages
