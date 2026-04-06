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
