"""
文件操作工具
提供 JSON 读写、目录管理等功能
"""
import json
from pathlib import Path
from typing import Any, Dict


def save_json(file_path: Path | str, data: Dict[str, Any], indent: int = 2) -> None:
    """
    保存数据为 JSON 文件

    Args:
        file_path: 文件路径
        data: 要保存的数据（字典）
        indent: 缩进空格数
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


def load_json(file_path: Path | str) -> Dict[str, Any]:
    """
    从 JSON 文件加载数据

    Args:
        file_path: 文件路径

    Returns:
        加载的数据字典
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_text(file_path: Path | str, content: str) -> None:
    """
    保存文本文件

    Args:
        file_path: 文件路径
        content: 文本内容
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def load_text(file_path: Path | str) -> str:
    """
    读取文本文件

    Args:
        file_path: 文件路径

    Returns:
        文本内容
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()
