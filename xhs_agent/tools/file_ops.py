"""
文件操作工具
替代Claude SDK的Read/Write/Edit工具
"""
import json
from pathlib import Path
from typing import Any, Dict


class FileOperations:
    """文件操作工具类"""

    @staticmethod
    def ensure_dir(path: Path | str) -> Path:
        """确保目录存在"""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def write_json(file_path: Path | str, data: Dict[str, Any], indent: int = 2) -> None:
        """写入JSON文件"""
        file_path = Path(file_path)
        FileOperations.ensure_dir(file_path.parent)

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)

    @staticmethod
    def read_json(file_path: Path | str) -> Dict[str, Any]:
        """读取JSON文件"""
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def write_text(file_path: Path | str, content: str) -> None:
        """写入文本文件"""
        file_path = Path(file_path)
        FileOperations.ensure_dir(file_path.parent)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

    @staticmethod
    def read_text(file_path: Path | str) -> str:
        """读取文本文件"""
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()

    @staticmethod
    def file_exists(file_path: Path | str) -> bool:
        """检查文件是否存在"""
        return Path(file_path).exists()

    @staticmethod
    def create_project_structure(project_dir: Path | str) -> Dict[str, Path]:
        """
        创建项目目录结构

        返回所有关键文件的路径
        """
        project_dir = Path(project_dir)
        FileOperations.ensure_dir(project_dir)
        FileOperations.ensure_dir(project_dir / "images")

        return {
            "project_dir": project_dir,
            "images_dir": project_dir / "images",
            "project_json": project_dir / "project.json",
            "xhs_research_json": project_dir / "xiaohongshu-research.json",
            "web_research_json": project_dir / "web-research.json",
            "research_summary_json": project_dir / "research-summary.json",
            "content_json": project_dir / "content.json",
            "publish_result_json": project_dir / "publish-result.json",
            "cover_image": project_dir / "images" / "cover.png",
            "image_1": project_dir / "images" / "image-1.png",
            "image_2": project_dir / "images" / "image-2.png",
        }

# 导出方便使用的函数
write_json = FileOperations.write_json
read_json = FileOperations.read_json
write_text = FileOperations.write_text
read_text = FileOperations.read_text
ensure_dir = FileOperations.ensure_dir
create_project_structure = FileOperations.create_project_structure
