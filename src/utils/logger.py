"""
统一日志配置模块

提供全局日志配置和模块级 logger 获取功能。
"""
import logging
import io
import sys


def _ensure_utf8_console_streams() -> None:
    if sys.platform != "win32":
        return

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if getattr(stream, "encoding", None) and stream.encoding.lower().replace("-", "") == "utf8":
            continue
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            continue
        setattr(
            sys,
            stream_name,
            io.TextIOWrapper(buffer, encoding="utf-8", errors="replace"),
        )


def setup_logging(level: int = logging.INFO, *, force: bool = False) -> None:
    """
    配置全局日志格式和输出

    Args:
        level: 日志级别，默认 INFO
    """
    _ensure_utf8_console_streams()
    logging.basicConfig(
        level=level,
        format='%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
        datefmt='%H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ],
        force=force,
    )


def get_logger(name: str) -> logging.Logger:
    """
    获取模块 logger
    
    Args:
        name: 模块名称，通常使用 __name__
        
    Returns:
        配置好的 Logger 实例
    """
    return logging.getLogger(name)
