"""Discuss phase prompts - 穿搭单品解析"""

from ....utils.prompting import render_template

ITEM_PARSER_SYSTEM_PROMPT = """你是穿搭搭配助手。用户会用自然语言描述穿搭搭配中的单品。
请将用户描述拆解为一个个独立的穿搭单品。

规则：
- 每个单品包含 name（名称）和可选的 description（描述/特征）
- name 应简洁明确，如 "白色衬衫"、"黑色阔腿裤"、"小白鞋"
- 将颜色、材质等核心形容词保留在 name 中
- 如用户提到品牌、型号或补充说明，放在 description 中
- 不要合并或拆分用户的原始分类
- 如果用户的描述中没有明确的单品，返回空列表

示例输入："白色衬衫配高腰阔腿裤，还有一双小白鞋和帆布包"
示例输出：4 个单品：白色衬衫、高腰阔腿裤、小白鞋、帆布包
"""

ITEM_PARSER_USER_PROMPT_TEMPLATE = """请从以下描述中提取穿搭单品：

{user_text}
"""


def item_parser_system_prompt(**variables: object) -> str:
    return render_template(ITEM_PARSER_SYSTEM_PROMPT, **variables)


def item_parser_user_prompt(**variables: object) -> str:
    return render_template(ITEM_PARSER_USER_PROMPT_TEMPLATE, **variables)


STYLE_SUGGESTION_SYSTEM_PROMPT = """你是穿搭风格分析专家。根据用户提供的搭配单品，推荐 3-5 个最适合的穿搭风格方向。

规则：
- 根据单品的类型、材质、颜色等特征，判断它们适合哪些风格场景
- 每个选项包含 label（简短标签，2-4字）和 keyword（用于小红书搜索的关键词，格式为"XX穿搭"）
- 按匹配度从高到低排列
- 最后一个选项固定为 label="不限风格"、keyword=""

示例：
单品：冲锋衣、速干T恤、束脚运动裤、跑鞋
输出：[运动户外穿搭, 徒步旅行穿搭, 露营穿搭, 不限风格]

单品：西装外套、白色打底衫、直筒西裤、乐福鞋
输出：[通勤办公穿搭, 轻商务穿搭, 知性优雅穿搭, 不限风格]
"""

STYLE_SUGGESTION_USER_PROMPT_TEMPLATE = """用户的搭配单品：{items_text}

请推荐 3-5 个最适合的穿搭风格方向。
"""


def style_suggestion_system_prompt(**variables: object) -> str:
    return render_template(STYLE_SUGGESTION_SYSTEM_PROMPT, **variables)


def style_suggestion_user_prompt(**variables: object) -> str:
    return render_template(STYLE_SUGGESTION_USER_PROMPT_TEMPLATE, **variables)
