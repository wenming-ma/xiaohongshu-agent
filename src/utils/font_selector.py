from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import Agent

from .providers import get_text_model
from .logger import get_logger

logger = get_logger(__name__)

FONTS_DIR = Path(__file__).parent.parent / "assets" / "fonts"

# 字体清单：file_name 是实际 TTF 文件名，font_family 是 ffmpeg FontName 需要的名字
FONT_CATALOG = [
    {
        "file_name": "KNBobohei-Bold.ttf",
        "font_family": "KN Bobohei",
        "display_name": "荆南波波黑",
        "style": "卡通俏皮，笔画带波浪感，适合搞笑、萌宠、可爱向内容",
    },
    {
        "file_name": "KNMaiyuan-Regular.ttf",
        "font_family": "KN Maiyuan",
        "display_name": "荆南麦圆体",
        "style": "萌系圆润，笔画两端饱满，适合儿童、亲子、萌系内容",
    },
    {
        "file_name": "ZCOOLKuaiLe-Regular.ttf",
        "font_family": "ZCOOL KuaiLe",
        "display_name": "站酷快乐体",
        "style": "活泼有趣，笔画灵活跳跃，适合轻松娱乐、美食探店",
    },
    {
        "file_name": "ZCOOLQingKeHuangYou-Regular.ttf",
        "font_family": "ZCOOL QingKe HuangYou",
        "display_name": "站酷庆科黄油体",
        "style": "全圆角处理，笨拙可爱，适合美食、甜品、温馨生活",
    },
    {
        "file_name": "LXGWWenKai-Medium.ttf",
        "font_family": "LXGW WenKai Medium",
        "display_name": "霞鹜文楷",
        "style": "文艺雅致的楷体风格，适合文化、读书、旅行、人文纪实",
    },
    {
        "file_name": "Yozai-Medium.ttf",
        "font_family": "Yozai Medium",
        "display_name": "悠哉字体",
        "style": "悠游自在的手写风，适合日常vlog、慢生活、手帐风格",
    },
    {
        "file_name": "Xiaolai-Regular.ttf",
        "font_family": "小賴字體",
        "display_name": "小赖字体",
        "style": "天然呆萌的手写风格，适合二次元、动漫、可爱日常",
    },
    {
        "file_name": "SmileySans-Oblique.ttf",
        "font_family": "Smiley Sans Oblique",
        "display_name": "得意黑",
        "style": "窄体斜字设计感强，融合手绘美术字造型，适合潮流、时尚、创意、科技",
    },
    {
        "file_name": "DouyinSansBold.ttf",
        "font_family": "DouyinSans",
        "display_name": "抖音美好体",
        "style": "简洁现代的品牌字体，适合知识分享、科普、测评、正式内容",
    },
    {
        "file_name": "LXGWMarkerGothic-Regular.ttf",
        "font_family": "LXGW Marker Gothic",
        "display_name": "霞鹜漫黑",
        "style": "马克笔手写风格，活泼个性，适合手工DIY、绘画、创意教程",
    },
]

# 用于快速查找
_CATALOG_BY_FILE = {f["file_name"]: f for f in FONT_CATALOG}

# 构建 system prompt 中的字体列表描述
_FONT_LIST_TEXT = "\n".join(
    f'- **{f["display_name"]}** (file: `{f["file_name"]}`): {f["style"]}'
    for f in FONT_CATALOG
)

FONT_SELECTOR_SYSTEM_PROMPT = f"""你是视频字幕字体选择专家。根据视频的话题、标题和描述，从以下可用字体中选择最匹配的一款。

## 可用字体

{_FONT_LIST_TEXT}

## 选择原则

1. **内容调性匹配**：字体风格应与视频内容的情绪和调性一致
2. **可读性优先**：字幕首要功能是让观众读懂，不要为了艺术性牺牲可读性
3. **平台风格**：目标平台是小红书，字体应符合年轻用户审美
4. **具体规则**：
   - 美食/烹饪类 → 优先圆润可爱的字体（快乐体、黄油体、波波黑）
   - 旅行/人文类 → 优先文艺雅致的字体（文楷、悠哉）
   - 时尚/潮流类 → 优先有设计感的字体（得意黑、抖音美好体）
   - 教程/知识类 → 优先清晰现代的字体（抖音美好体、得意黑）
   - 萌宠/可爱类 → 优先卡通萌系字体（波波黑、麦圆体、小赖）
   - DIY/手工类 → 优先手写风格（漫黑、悠哉）

## 输出要求

只输出 `font_file`（必须是上述列表中的 file 值）和 `reason`（一句话说明选择理由）。
"""


class FontSelection(BaseModel):
    font_file: str
    reason: str


class FontSelectorAgent:

    def __init__(self):
        self._agent: Agent | None = None

    def _init_agent(self) -> None:
        if self._agent is None:
            self._agent = Agent(
                model=get_text_model(),
                output_type=FontSelection,
                system_prompt=FONT_SELECTOR_SYSTEM_PROMPT,
            )

    async def select_font(
        self,
        topic: str,
        video_title: str = "",
        video_description: str = "",
    ) -> FontSelection:
        self._init_agent()

        prompt = f"话题: {topic}"
        if video_title:
            prompt += f"\n视频标题: {video_title}"
        if video_description:
            prompt += f"\n视频描述: {video_description[:300]}"

        try:
            result = await self._agent.run(prompt)
            selection = result.output

            # 校验返回的 font_file 在目录中存在
            font_path = FONTS_DIR / selection.font_file
            if not font_path.exists():
                logger.warning(f"LLM 选择的字体文件不存在: {selection.font_file}，回退默认")
                return _default_selection()

            logger.info(f"字体选择: {selection.font_file} — {selection.reason}")
            return selection

        except Exception as e:
            logger.warning(f"字体选择失败，回退默认: {e}")
            return _default_selection()


def _default_selection() -> FontSelection:
    return FontSelection(
        font_file="ZCOOLKuaiLe-Regular.ttf",
        reason="默认回退字体",
    )


def get_font_info(font_file: str) -> dict | None:
    """根据文件名获取字体信息"""
    return _CATALOG_BY_FILE.get(font_file)


def get_fonts_dir() -> Path:
    return FONTS_DIR
