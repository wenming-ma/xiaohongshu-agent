"""
Prompt 加载工具

从 YAML 文件加载 prompt 配置，支持：
- 版本管理
- 变量模板
- 多 prompt 组织
"""
import yaml
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> dict[str, Any]:
    """
    加载 prompt 配置文件

    Args:
        name: prompt 名称（不含 .yaml 后缀）

    Returns:
        完整的 prompt 配置字典
    """
    path = PROMPTS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在: {path}")

    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_system_prompt(name: str, **variables) -> str:
    """
    获取 system prompt 文本，支持变量替换

    Args:
        name: prompt 名称
        **variables: 要替换的变量

    Returns:
        处理后的 system prompt 文本

    Example:
        >>> get_system_prompt("research", topic="西安避坑", audience="求职者")
    """
    config = load_prompt(name)
    prompt = config.get('system_prompt', '')

    # 变量替换
    if variables:
        for key, value in variables.items():
            prompt = prompt.replace(f"{{{key}}}", str(value))

    return prompt


def get_prompt_version(name: str) -> str:
    """获取 prompt 版本号"""
    config = load_prompt(name)
    return config.get('version', 'unknown')


def get_user_prompt(name: str, **variables) -> str:
    """
    获取 user prompt 模板，支持变量替换

    Args:
        name: prompt 名称
        **variables: 要替换的变量

    Returns:
        处理后的 user prompt 文本

    Example:
        >>> get_user_prompt("research", topic="西安避坑", target_audience="求职者")
    """
    config = load_prompt(name)
    template = config.get('user_prompt_template', '')

    # 变量替换
    if variables:
        for key, value in variables.items():
            template = template.replace(f"{{{key}}}", str(value))

    return template


def get_prompt_metadata(name: str) -> dict[str, Any]:
    """获取 prompt 元数据（不含 prompt 内容）"""
    config = load_prompt(name)
    return {k: v for k, v in config.items() if k not in ('system_prompt', 'user_prompt_template')}


def get_prompt_field(name: str, field: str, **variables) -> str:
    """
    获取 prompt 配置中的任意字段，支持变量替换

    Args:
        name: prompt 名称
        field: 字段名称
        **variables: 要替换的变量

    Returns:
        处理后的文本

    Example:
        >>> get_prompt_field("image", "gemini_operator_prompt")
        >>> get_prompt_field("image", "gemini_operation_template", prompt="生成图片...")
    """
    config = load_prompt(name)
    template = config.get(field, '')

    # 变量替换
    if variables:
        for key, value in variables.items():
            template = template.replace(f"{{{key}}}", str(value))

    return template
