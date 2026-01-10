"""
统一日志配置模块

提供全局日志配置和模块级 logger 获取功能。
"""
import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """
    配置全局日志格式和输出
    
    Args:
        level: 日志级别，默认 INFO
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
        datefmt='%H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
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
