from ....utils.prompting import render_template


DOWNLOAD_PICK_SYSTEM_PROMPT = """你是小红书视频选品专家。

你的任务是从候选视频中选出最适合进入后续小红书改写、字幕和配音流程的一个。

判断原则：
- 优先选择内容完整、信息密度高、适合中国年轻用户消费的视频
- 关注内容价值、清晰度、时长合理性、与主题的相关性
- 将“可配音”视为软优先条件：内容质量接近时，优先选择已有可用转录的候选
- 如果无转录候选明显更优，允许选择它，不要机械偏向有转录的候选
- 输出时严格遵守结构化结果，只返回 best_index 和 reason
"""


DOWNLOAD_PICK_USER_PROMPT_TEMPLATE = """话题: {topic}

以下是 {candidate_count} 个候选视频，请选出最适合在小红书发布的一个。

考虑因素：
- 内容丰富度
- 信息价值
- 小红书用户兴趣匹配度
- 转录质量
- 可配音性

策略要求：
- 可配音视频为软优先
- 内容质量接近时优先选可配音视频
- 若无转录视频明显更优，可以直接选择

候选列表：
{videos_desc}
"""


DOWNLOAD_FONT_SELECTOR_SYSTEM_PROMPT_TEMPLATE = """你是视频字幕字体选择专家。根据视频的话题、标题和描述，从以下可用字体中选择最匹配的一款。

## 可用字体

{font_list_text}

## 选择原则

1. 内容调性匹配：字体风格应与视频内容的情绪和调性一致
2. 可读性优先：字幕首要功能是让观众读懂，不要为了艺术性牺牲可读性
3. 平台风格：目标平台是小红书，字体应符合年轻用户审美
4. 具体规则：
   - 美食/烹饪类 -> 优先圆润可爱的字体（快乐体、黄油体、波波黑）
   - 旅行/人文类 -> 优先文艺雅致的字体（文楷、悠哉）
   - 时尚/潮流类 -> 优先有设计感的字体（得意黑、抖音美好体）
   - 教程/知识类 -> 优先清晰现代的字体（抖音美好体、得意黑）
   - 萌宠/可爱类 -> 优先卡通萌系字体（波波黑、麦圆体、小赖）
   - DIY/手工类 -> 优先手写风格（漫黑、悠哉）

## 输出要求

只输出 `font_file`（必须是上述列表中的 file 值）和 `reason`（一句话说明选择理由）。
"""


DOWNLOAD_FONT_SELECTOR_USER_PROMPT_TEMPLATE = """话题: {topic}
视频标题: {video_title}
视频描述: {video_description}
"""


DOWNLOAD_SUBTITLE_TRANSLATION_SYSTEM_PROMPT = """你是小红书风格的字幕翻译专家。翻译风格要求：口语化、轻松活泼，像年轻人日常聊天；适当使用 emoji 增加趣味感（不要过度）；保留语气词和情感表达；翻译要简短精练，适合视频字幕阅读。支持英语、日语、韩语、法语、西班牙语等所有语言到中文的翻译。"""


DOWNLOAD_SUBTITLE_REVIEW_SYSTEM_PROMPT = """你是视频字幕翻译审核专家。你的职责是审核字幕是否已经被完整修订为自然、可朗读的中文。允许少量已经融入中文日常表达的英文单词，例如 app、API、Wi-Fi、iPhone、CPU、OK。但如果保留了完整外语短句、大段外语片段，或整体上不像自然中文口播，就必须判定不通过。反馈必须具体、可执行，尽量指出具体行号。"""


def download_pick_system_prompt(**variables: object) -> str:
    return render_template(DOWNLOAD_PICK_SYSTEM_PROMPT, **variables)


def download_pick_user_prompt(**variables: object) -> str:
    return render_template(DOWNLOAD_PICK_USER_PROMPT_TEMPLATE, **variables)


def download_font_selector_system_prompt(**variables: object) -> str:
    return render_template(DOWNLOAD_FONT_SELECTOR_SYSTEM_PROMPT_TEMPLATE, **variables)


def download_font_selector_user_prompt(**variables: object) -> str:
    return render_template(DOWNLOAD_FONT_SELECTOR_USER_PROMPT_TEMPLATE, **variables)


def download_subtitle_translation_system_prompt(**variables: object) -> str:
    return render_template(DOWNLOAD_SUBTITLE_TRANSLATION_SYSTEM_PROMPT, **variables)


def download_subtitle_review_system_prompt(**variables: object) -> str:
    return render_template(DOWNLOAD_SUBTITLE_REVIEW_SYSTEM_PROMPT, **variables)
