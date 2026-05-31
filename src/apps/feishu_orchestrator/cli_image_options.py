from __future__ import annotations

import argparse
from typing import Any


def add_image_request_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--image-count", type=int, default=None, help="可选，期望生成的图片张数")
    parser.add_argument(
        "--reference-image",
        action="append",
        default=[],
        help="可重复传入的参考图路径，交给图片 Agent 作为硬性视觉约束",
    )


def add_image_run_option_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--research-min-posts", type=int, default=None, help="本次研究最少调研帖子数")
    parser.add_argument("--research-validation-retries", type=int, default=None, help="本次研究验证最多轮数")
    parser.add_argument("--research-min-key-infos", type=int, default=None, help="本次研究最少关键结论数")
    parser.add_argument("--research-min-cases", type=int, default=None, help="本次研究最少案例数")
    parser.add_argument("--image-max-retries", type=int, default=None, help="本次单图生成最大重试次数")
    parser.add_argument("--image-size", default=None, help="本次图片尺寸等级，例如 2K 或 4K")
    parser.add_argument("--image-aspect-ratio", default=None, help="本次图片比例，例如 3:4")
    parser.add_argument(
        "--image-reference-mode",
        choices=["gemini_content", "none"],
        default=None,
        help="参考图传入模式；默认 gemini_content，none 表示只写入 prompt 不随请求上传",
    )
    parser.add_argument(
        "--disable-keyword-prompt-expansion",
        action="store_true",
        help="关闭基于 subject/action/location/camera/lighting/style/reference 的关键词扩展步骤",
    )


def build_image_post_run_options_from_args(args: Any) -> ImagePostRunOptions:
    from src.orchestration.run_options import ImagePostRunOptions

    options = ImagePostRunOptions()
    if getattr(args, "research_min_posts", None) is not None:
        options.research.min_posts_researched = args.research_min_posts
    if getattr(args, "research_validation_retries", None) is not None:
        options.research.validation_max_retries = args.research_validation_retries
    if getattr(args, "research_min_key_infos", None) is not None:
        options.research.min_key_infos = args.research_min_key_infos
    if getattr(args, "research_min_cases", None) is not None:
        options.research.min_cases = args.research_min_cases
    if getattr(args, "image_max_retries", None) is not None:
        options.image.max_retries = args.image_max_retries
    if getattr(args, "image_size", None) is not None:
        options.image.image_size = args.image_size
    if getattr(args, "image_aspect_ratio", None) is not None:
        options.image.aspect_ratio = args.image_aspect_ratio
    if getattr(args, "image_reference_mode", None) is not None:
        options.image.reference_mode = args.image_reference_mode
    if getattr(args, "disable_keyword_prompt_expansion", False):
        options.image.keyword_prompt_expansion = False
    return options
