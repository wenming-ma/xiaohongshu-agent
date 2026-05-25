"""Probe Android Xiaohongshu QR-login album support.

Usage:
    uv run python workshop/image_post/android_qr_probe.py path/to/login-qr.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.agents.shared.login.android_qr import (
    AndroidQrLoginAutomator,
    AndroidQrLoginConfig,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path, help="Path to the QR screenshot/image to push to Android.")
    parser.add_argument("--serial", default=None, help="ADB serial. Defaults to ANDROID_SERIAL/XHS_ANDROID_SERIAL.")
    parser.add_argument("--package", default="com.xingin.xhs", help="Xiaohongshu Android package name.")
    args = parser.parse_args()

    config = AndroidQrLoginConfig.from_env()
    config = AndroidQrLoginConfig(
        enabled=config.enabled,
        serial=args.serial or config.serial,
        package_name=args.package,
        remote_dir=config.remote_dir,
        launch_wait_seconds=config.launch_wait_seconds,
        ui_wait_seconds=config.ui_wait_seconds,
    )
    result = AndroidQrLoginAutomator(config=config).attempt_scan_from_album(args.image)
    print(f"success={result.success}")
    print(f"status={result.status}")
    print(f"message={result.message}")
    if result.remote_image_path:
        print(f"remote_image_path={result.remote_image_path}")
    return 0 if result.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
