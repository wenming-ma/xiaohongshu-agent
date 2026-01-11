"""
专用验证器模块
每个验证器负责特定的验证任务，便于扩展和复用

外部验证器/内部验证器的基类与结果类型。
"""
# 外部验证器（装饰器模式）
from .external_base import ExternalValidator, ValidationError

# 内部验证器（循环内验证）
from .internal_base import InternalValidator, InternalValidationResult

__all__ = [
    # 外部验证器（装饰器模式）
    "ExternalValidator",
    "ValidationError",
    # 内部验证器（循环内验证）
    "InternalValidator",
    "InternalValidationResult",
]
