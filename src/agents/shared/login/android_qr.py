"""Android-side helper for QR-code login automation.

The module is intentionally independent from the LoginAgent prompt loop. It can
be tested without a phone, and the real device path fails closed so the caller
can retry, refresh the QR code, or return a structured failure.
"""

from __future__ import annotations

import os
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from pydantic_ai import Tool

from ....utils.logger import get_logger

logger = get_logger(__name__)

AdbRunner = Callable[[list[str]], str]


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _sanitize_remote_name(path: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.name).strip("._")
    return name or "xhs-login-qr.png"


@dataclass(frozen=True)
class AndroidQrLoginConfig:
    enabled: bool = True
    serial: str | None = None
    package_name: str = "com.xingin.xhs"
    remote_dir: str = "/sdcard/Pictures/xhs-auto-login"
    launch_wait_seconds: float = 3.0
    ui_wait_seconds: float = 20.0

    @classmethod
    def from_env(cls) -> "AndroidQrLoginConfig":
        return cls(
            enabled=_env_bool("XHS_ANDROID_QR_ENABLED", True),
            serial=os.getenv("ANDROID_SERIAL") or os.getenv("XHS_ANDROID_SERIAL") or None,
            package_name=os.getenv("XHS_ANDROID_XHS_PACKAGE", "com.xingin.xhs"),
            remote_dir=os.getenv("XHS_ANDROID_QR_REMOTE_DIR", "/sdcard/Pictures/xhs-auto-login"),
        )


@dataclass(frozen=True)
class AndroidQrLoginResult:
    success: bool
    status: str
    message: str
    remote_image_path: str | None = None


def classify_android_login_hierarchy(hierarchy: str) -> str:
    if _contains_any_text(
        hierarchy,
        [
            "failed login",
            "login failed",
            "failed to log in",
            "登录失败",
            "登入失败",
        ],
    ):
        return "login_failed"
    if _contains_any_text(hierarchy, ["expired", "过期", "二维码已失效", "QR code has expired"]):
        return "qr_expired"
    if _contains_any_text(
        hierarchy,
        [
            "No QR code was identified",
            "Click the screen to continue scanning",
            "未识别到二维码",
            "无法识别二维码",
            "没有识别到二维码",
        ],
    ):
        return "qr_not_identified"
    if _contains_any_text(
        hierarchy,
        [
            "com.android.permissioncontroller",
            "permission_allow_button",
            "permission_allow_foreground_only_button",
            "requires the following permission",
            "Allow only while using the app",
            "While using the app",
        ],
    ):
        return "android_permission"
    if _contains_any_text(hierarchy, ["com.coloros.gallery3d"]):
        return "coloros_gallery"
    if _contains_any_text(hierarchy, ["Allow rednote to access photos", "照片和视频", "photos and media"]):
        return "photo_permission"
    if _contains_any_text(hierarchy, ["打开通知", "通知", "热门笔记", "确认"]):
        return "startup_dialog"
    if _contains_any_text(hierarchy, ["Login confirmation", "Log in to rednote desktop", "登录确认"]):
        if _contains_any_text(hierarchy, ["Log in（", "登录（", "确认（"]):
            return "confirmation_countdown"
        if _contains_any_text(hierarchy, ['content-desc="Log in"', 'text="Log in"', 'content-desc="登录"', 'text="登录"']):
            return "confirmation_ready"
        return "confirmation_page"
    if _contains_any_text(hierarchy, ['content-desc="menu"', 'content-desc="Home"', 'content-desc="Me"']):
        return "xhs_home"
    if _is_xhs_album_picker_hierarchy(hierarchy):
        return "album_picker"
    if _contains_any_text(hierarchy, ["com.xingin.xhs.redscanner:id/llMyPhoto", "Album", "相册"]):
        return "scanner_ready"
    if _contains_any_text(hierarchy, ["Scan", "扫一扫", "扫码"]):
        return "scan_entry_visible"
    return "unknown"


def build_android_qr_tool_message(
    *,
    success: bool,
    status: str,
    message: str,
    screenshot_path: Path,
    remote_image_path: str | None,
) -> str:
    if success:
        return (
            "Android 自动扫码成功。\n"
            f"- status: {status}\n"
            f"- screenshot: {screenshot_path}\n"
            f"- remote_image_path: {remote_image_path or 'N/A'}\n"
            f"- detail: {message}\n"
            "下一步：刷新或检查当前网页登录状态，确认是否已经登录。"
        )

    if status == "confirmation_submitted":
        return (
            "Android 已提交登录确认。\n"
            f"- status: {status}\n"
            f"- screenshot: {screenshot_path}\n"
            f"- remote_image_path: {remote_image_path or 'N/A'}\n"
            f"- detail: {message}\n"
            "下一步：检查当前网页登录状态；如果网页仍未登录，重新生成二维码后重试或返回失败。"
        )

    if status == "login_failed":
        return (
            "Android 登录确认后失败。\n"
            f"- status: {status}\n"
            f"- screenshot: {screenshot_path}\n"
            f"- remote_image_path: {remote_image_path or 'N/A'}\n"
            f"- detail: {message}\n"
            "下一步：重新生成二维码后重试；不要把本次手机端确认当作登录成功。"
        )

    return (
        "Android 自动扫码未完成。\n"
        f"- status: {status}\n"
        f"- screenshot: {screenshot_path}\n"
        f"- remote_image_path: {remote_image_path or 'N/A'}\n"
        f"- detail: {message}\n"
        "下一步：刷新或重新生成二维码后重试；如果仍无法全自动完成，返回结构化失败。"
    )


class AndroidQrLoginToolset:
    """Small Android QR-login actions for a dedicated login agent."""

    def __init__(self, automator: AndroidQrLoginAutomator | None = None):
        self.automator = automator or AndroidQrLoginAutomator()

    def get_tools(self) -> list[Tool]:
        return [
            Tool(self.inspect_android_ui, takes_ctx=False),
            Tool(self.push_qr_to_android_gallery, takes_ctx=False),
            Tool(self.open_xhs_scanner, takes_ctx=False),
            Tool(self.open_scanner_album, takes_ctx=False),
            Tool(self.select_latest_album_image, takes_ctx=False),
            Tool(self.submit_xhs_login_confirmation, takes_ctx=False),
        ]

    def inspect_android_ui(self) -> str:
        """Inspect the connected Android phone and return package/activity/state as JSON."""
        try:
            device = self.automator._connect_uiautomator()
            return self._dump(self._snapshot(device))
        except Exception as exc:
            return self._dump({"ok": False, "state": "uiautomator_unavailable", "error": self._error(exc)})

    def push_qr_to_android_gallery(self, image_path: str) -> str:
        """Push a local QR screenshot to Android gallery and refresh MediaStore."""
        try:
            remote = self.automator.push_image_to_gallery(Path(image_path))
            return self._dump({"ok": True, "state": "qr_pushed", "remote_image_path": remote})
        except FileNotFoundError as exc:
            return self._dump({"ok": False, "state": "missing_image", "error": str(exc)})
        except Exception as exc:
            return self._dump({"ok": False, "state": "adb_error", "error": self._error(exc)})

    def open_xhs_scanner(self) -> str:
        """Open Xiaohongshu and navigate to the scanner page if possible."""
        try:
            device = self.automator._connect_uiautomator()
            device.screen_on()
            device.app_start(self.automator.config.package_name, stop=False)
            device.sleep(self.automator.config.launch_wait_seconds)
            ok = self.automator._open_scanner(device)
            snapshot = self._snapshot(device)
            snapshot["ok"] = bool(ok)
            if not ok and not snapshot.get("error"):
                snapshot["error"] = "scan entry not found"
            return self._dump(snapshot)
        except Exception as exc:
            return self._dump({"ok": False, "state": "open_scanner_failed", "error": self._error(exc)})

    def open_scanner_album(self) -> str:
        """Tap the scanner Album entry and handle Android permission prompts."""
        try:
            device = self.automator._connect_uiautomator()
            ok = self.automator._tap_album_entry(device)
            device.sleep(1.0)
            if self.automator._allow_android_permission_if_present(device):
                device.sleep(1.0)
            snapshot = self._snapshot(device)
            snapshot["ok"] = bool(ok)
            if not ok and not snapshot.get("error"):
                snapshot["error"] = "album entry not found"
            return self._dump(snapshot)
        except Exception as exc:
            return self._dump({"ok": False, "state": "open_album_failed", "error": self._error(exc)})

    def select_latest_album_image(self) -> str:
        """Select the first large image cell in the XHS album picker."""
        try:
            device = self.automator._connect_uiautomator()
            ok = self.automator._tap_first_album_image(device)
            device.sleep(1.0)
            snapshot = self._snapshot(device)
            snapshot["ok"] = bool(ok)
            if not ok and not snapshot.get("error"):
                snapshot["error"] = "album image not found"
            return self._dump(snapshot)
        except Exception as exc:
            return self._dump({"ok": False, "state": "select_album_image_failed", "error": self._error(exc)})

    def submit_xhs_login_confirmation(self) -> str:
        """Wait for and submit the phone-side XHS login confirmation."""
        try:
            device = self.automator._connect_uiautomator()
            status = self.automator._tap_login_confirmation(device)
            snapshot = self._snapshot(device)
            snapshot["ok"] = status == "submitted"
            snapshot["submit_status"] = status
            return self._dump(snapshot)
        except Exception as exc:
            return self._dump({"ok": False, "state": "submit_confirmation_failed", "error": self._error(exc)})

    def _snapshot(self, device) -> dict[str, object]:
        hierarchy = device.dump_hierarchy(compressed=False)
        app = self._safe_app_current(device)
        return {
            "ok": True,
            "state": classify_android_login_hierarchy(hierarchy),
            "package": app.get("package", ""),
            "activity": app.get("activity", ""),
            "visible_texts": _extract_visible_texts(hierarchy),
        }

    @staticmethod
    def _safe_app_current(device) -> dict[str, str]:
        try:
            current = device.app_current()
        except Exception:
            return {}
        if isinstance(current, dict):
            return {str(k): str(v) for k, v in current.items()}
        return {}

    @staticmethod
    def _dump(payload: dict[str, object]) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _error(exc: Exception) -> str:
        return f"{type(exc).__name__}: {str(exc)[:200]}"


class AndroidQrLoginAutomator:
    def __init__(
        self,
        config: AndroidQrLoginConfig | None = None,
        adb_runner: AdbRunner | None = None,
    ) -> None:
        self.config = config or AndroidQrLoginConfig.from_env()
        self._adb_runner = adb_runner or self._run_adb

    def push_image_to_gallery(self, image_path: Path) -> str:
        if not image_path.exists():
            raise FileNotFoundError(str(image_path))

        remote_path = f"{self.config.remote_dir.rstrip('/')}/{_sanitize_remote_name(image_path)}"
        self._adb(["shell", "mkdir", "-p", self.config.remote_dir])
        self._adb(["push", str(image_path), remote_path])
        self._adb(
            [
                "shell",
                "am",
                "broadcast",
                "-a",
                "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                "-d",
                f"file://{remote_path}",
            ]
        )
        return remote_path

    def attempt_scan_from_album(self, image_path: Path) -> AndroidQrLoginResult:
        if not self.config.enabled:
            return AndroidQrLoginResult(False, "disabled", "Android QR automation is disabled.")

        try:
            remote_path = self.push_image_to_gallery(image_path)
        except FileNotFoundError as exc:
            return AndroidQrLoginResult(False, "missing_image", f"QR image not found: {exc}")
        except Exception as exc:
            return AndroidQrLoginResult(False, "adb_error", f"Failed to push QR image: {exc}")

        try:
            device = self._connect_uiautomator()
        except Exception as exc:
            return AndroidQrLoginResult(
                False,
                "uiautomator_unavailable",
                f"uiautomator2 is unavailable or the device is not controllable: {exc}",
                remote_image_path=remote_path,
            )

        try:
            return self._probe_xhs_album_scan(device, remote_path)
        except Exception as exc:
            logger.exception("Android QR scan probe failed")
            return AndroidQrLoginResult(
                False,
                "probe_failed",
                f"Android QR scan probe failed: {type(exc).__name__}: {str(exc)[:200]}",
                remote_image_path=remote_path,
            )

    def _probe_xhs_album_scan(self, device, remote_path: str) -> AndroidQrLoginResult:
        device.screen_on()
        device.app_start(self.config.package_name, stop=False)
        device.sleep(self.config.launch_wait_seconds)

        if not self._open_scanner(device):
            return AndroidQrLoginResult(
                False,
                "scan_entry_not_found",
                "Launched Xiaohongshu, but the scan entry was not found.",
                remote_image_path=remote_path,
            )

        if not self._tap_album_entry(device):
            return AndroidQrLoginResult(
                False,
                "album_entry_not_found",
                "Opened Xiaohongshu scanner, but the Album entry was not found.",
                remote_image_path=remote_path,
            )

        device.sleep(1.0)
        self._allow_photo_permission_if_present(device)
        device.sleep(1.0)

        if not self._tap_first_album_image(device):
            return AndroidQrLoginResult(
                False,
                "album_image_not_found",
                "Opened the Album picker, but no selectable image thumbnail was found.",
                remote_image_path=remote_path,
            )

        confirmation_status = self._tap_login_confirmation(device)
        if confirmation_status == "submitted":
            return AndroidQrLoginResult(
                False,
                "confirmation_submitted",
                "Xiaohongshu QR image was selected from Album and the login confirmation was submitted. Verify the web page login state next.",
                remote_image_path=remote_path,
            )
        if confirmation_status == "login_failed":
            return AndroidQrLoginResult(
                False,
                "login_failed",
                "Xiaohongshu reported failed login after the mobile confirmation was submitted.",
                remote_image_path=remote_path,
            )

        hierarchy = device.dump_hierarchy(compressed=False)
        if self._contains_any(hierarchy, ["expired", "过期", "二维码已失效", "QR code has expired"]):
            return AndroidQrLoginResult(
                False,
                "qr_expired",
                "Xiaohongshu recognized the QR image, but the QR code is expired.",
                remote_image_path=remote_path,
            )
        if self._qr_not_identified_visible(hierarchy):
            return AndroidQrLoginResult(
                False,
                "qr_not_identified",
                "Xiaohongshu selected the album image, but no QR code was identified.",
                remote_image_path=remote_path,
            )

        return AndroidQrLoginResult(
            False,
            "confirmation_not_found",
            "Xiaohongshu selected the QR image, but no login confirmation button was found.",
            remote_image_path=remote_path,
        )

    def _open_scanner(self, device) -> bool:
        if self._album_entry_visible(device):
            return True

        scan_xpaths = [
            '//*[contains(@text, "Scan")]',
            '//*[contains(@content-desc, "Scan")]',
            '//*[contains(@text, "扫一扫")]',
            '//*[contains(@content-desc, "扫一扫")]',
            '//*[contains(@text, "扫码")]',
            '//*[contains(@content-desc, "扫码")]',
        ]
        menu_xpaths = [
            '//*[contains(@content-desc, "menu")]',
            '//*[contains(@content-desc, "Menu")]',
            '//*[contains(@text, "menu")]',
            '//*[contains(@text, "Menu")]',
        ]

        if self._click_first_xpath(device, scan_xpaths):
            return self._wait_for_album_entry(device)

        if self._click_first_xpath(device, menu_xpaths):
            if self._wait_for_xpath(device, scan_xpaths, timeout_seconds=5):
                if self._click_first_xpath(device, scan_xpaths):
                    return self._wait_for_album_entry(device)

        width, height = self._display_size(device)
        device.click(round(width * 0.06), round(height * 0.065))

        if self._wait_for_xpath(device, scan_xpaths, timeout_seconds=5):
            if self._click_first_xpath(device, scan_xpaths):
                return self._wait_for_album_entry(device)

        return self._album_entry_visible(device)

    def _tap_album_entry(self, device) -> bool:
        selectors = [
            {"resourceId": "com.xingin.xhs.redscanner:id/llMyPhoto"},
            {"text": "Album"},
            {"text": "相册"},
        ]
        if self._click_first_selector(device, selectors):
            return True
        return self._click_first_xpath(
            device,
            [
                '//*[contains(@text, "Album")]',
                '//*[contains(@content-desc, "Album")]',
                '//*[contains(@text, "相册")]',
                '//*[contains(@content-desc, "相册")]',
            ],
        )

    def _allow_photo_permission_if_present(self, device) -> bool:
        return self._allow_android_permission_if_present(device)

    def _allow_android_permission_if_present(self, device) -> bool:
        selectors = [
            {"resourceId": "com.android.permissioncontroller:id/permission_allow_button"},
            {"resourceId": "com.android.permissioncontroller:id/permission_allow_foreground_only_button"},
            {"resourceId": "com.android.permissioncontroller:id/permission_allow_one_time_button"},
            {"text": "Allow"},
            {"text": "While using the app"},
            {"text": "Allow only while using the app"},
            {"text": "允许"},
            {"text": "全部允许"},
            {"text": "允许访问所有照片"},
            {"text": "使用应用时允许"},
            {"text": "仅限本次使用"},
        ]
        if self._click_first_selector(device, selectors):
            return True
        return self._click_first_xpath(
            device,
            [
                '//*[contains(@text, "Allow")]',
                '//*[contains(@text, "While using")]',
                '//*[contains(@text, "允许")]',
                '//*[contains(@text, "全部")]',
            ],
        )

    def _tap_first_album_image(self, device) -> bool:
        hierarchy = device.dump_hierarchy(compressed=False)
        candidates: list[tuple[int, int, int, int]] = []
        for node in re.findall(r"<node\b[^>]+/>", hierarchy):
            if 'clickable="true"' not in node:
                continue
            if 'class="android.widget.ImageView"' not in node:
                continue
            bounds = self._node_bounds(node)
            if bounds is None:
                continue
            left, top, right, bottom = bounds
            area = (right - left) * (bottom - top)
            if top < 260 or area < 30_000:
                continue
            candidates.append(bounds)

        if not candidates:
            return False

        left, top, right, bottom = sorted(candidates, key=lambda box: (box[1], box[0]))[0]
        device.click(round((left + right) / 2), round((top + bottom) / 2))
        return True

    def _tap_login_confirmation(self, device) -> str:
        for attempt in range(max(1, round(self.config.ui_wait_seconds))):
            hierarchy = device.dump_hierarchy(compressed=False)
            if self._login_failed_visible(hierarchy):
                return "login_failed"
            if not self._contains_any(
                hierarchy,
                ["Login confirmation", "Log in to rednote desktop", "登录确认", "电脑", "desktop"],
            ):
                if attempt < round(self.config.ui_wait_seconds) - 1:
                    device.sleep(1.0)
                    continue
                return "not_found"

            if self._click_first_xpath(
                device,
                [
                    '//*[@content-desc="Log in"]',
                    '//*[@text="Log in"]',
                    '//*[@content-desc="登录"]',
                    '//*[@text="登录"]',
                    '//*[@content-desc="确认登录"]',
                    '//*[@text="确认登录"]',
                    '//*[@content-desc="确认"]',
                    '//*[@text="确认"]',
                ],
            ):
                return self._wait_after_confirmation_submit(device)

            if attempt < round(self.config.ui_wait_seconds) - 1:
                device.sleep(1.0)

        return "not_found"

    def _wait_after_confirmation_submit(self, device) -> str:
        for _ in range(max(1, round(self.config.ui_wait_seconds))):
            device.sleep(1.0)
            hierarchy = device.dump_hierarchy(compressed=False)
            if self._login_failed_visible(hierarchy):
                return "login_failed"
            if not self._contains_any(
                hierarchy,
                ["Login confirmation", "Log in to rednote desktop", "登录确认"],
            ):
                return "submitted"
        return "not_found"

    def _login_failed_visible(self, hierarchy: str) -> bool:
        return self._contains_any(
            hierarchy,
            [
                "failed login",
                "login failed",
                "failed to log in",
                "登录失败",
                "登入失败",
            ],
        )

    def _qr_not_identified_visible(self, hierarchy: str) -> bool:
        return self._contains_any(
            hierarchy,
            [
                "No QR code was identified",
                "Click the screen to continue scanning",
                "未识别到二维码",
                "无法识别二维码",
                "没有识别到二维码",
            ],
        )

    def _album_entry_visible(self, device) -> bool:
        selectors = [
            {"resourceId": "com.xingin.xhs.redscanner:id/llMyPhoto"},
            {"text": "Album"},
            {"text": "相册"},
        ]
        return self._selector_exists(device, selectors) or any(
            self._xpath_exists(device, xpath)
            for xpath in [
                '//*[contains(@text, "Album")]',
                '//*[contains(@content-desc, "Album")]',
                '//*[contains(@text, "相册")]',
                '//*[contains(@content-desc, "相册")]',
            ]
        )

    def _wait_for_album_entry(self, device) -> bool:
        for _ in range(max(1, round(self.config.ui_wait_seconds))):
            if self._album_entry_visible(device):
                return True
            hierarchy = device.dump_hierarchy(compressed=False)
            if classify_android_login_hierarchy(hierarchy) == "android_permission":
                self._allow_android_permission_if_present(device)
            device.sleep(1.0)
        return False

    def _wait_for_xpath(self, device, xpaths: Iterable[str], timeout_seconds: int) -> bool:
        for _ in range(max(1, timeout_seconds)):
            if any(self._xpath_exists(device, xpath) for xpath in xpaths):
                return True
            device.sleep(1.0)
        return False

    def _selector_exists(self, device, selectors: Iterable[dict[str, str]]) -> bool:
        for selector in selectors:
            try:
                if device(**selector).exists:
                    return True
            except Exception:
                continue
        return False

    def _click_first_selector(self, device, selectors: Iterable[dict[str, str]]) -> bool:
        for selector in selectors:
            try:
                element = device(**selector)
                if element.exists:
                    element.click()
                    return True
            except Exception:
                continue
        return False

    def _click_first_xpath(self, device, xpaths: Iterable[str]) -> bool:
        for xpath in xpaths:
            try:
                element = device.xpath(xpath)
                if element.exists:
                    element.click()
                    return True
            except Exception:
                continue
        return False

    def _xpath_exists(self, device, xpath: str) -> bool:
        try:
            return bool(device.xpath(xpath).exists)
        except Exception:
            return False

    def _display_size(self, device) -> tuple[int, int]:
        info = getattr(device, "info", {}) or {}
        width = int(info.get("displayWidth") or info.get("display_width") or 1440)
        height = int(info.get("displayHeight") or info.get("display_height") or 3040)
        return width, height

    @staticmethod
    def _contains_any(text: str, needles: Iterable[str]) -> bool:
        return _contains_any_text(text, needles)

    @staticmethod
    def _node_bounds(node: str) -> tuple[int, int, int, int] | None:
        match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if not match:
            return None
        return tuple(int(part) for part in match.groups())

    def _connect_uiautomator(self):
        try:
            import uiautomator2 as u2
        except ImportError as exc:
            raise RuntimeError("install uiautomator2 to enable Android UI control") from exc

        if self.config.serial:
            return u2.connect(self.config.serial)
        return u2.connect()

    def _adb(self, args: list[str]) -> str:
        command = ["adb"]
        if self.config.serial:
            command.extend(["-s", self.config.serial])
        command.extend(args)
        return self._adb_runner(command)

    @staticmethod
    def _run_adb(command: list[str]) -> str:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"{' '.join(command)} failed: {detail}")
        return result.stdout.strip()


def _contains_any_text(text: str, needles: Iterable[str]) -> bool:
    lower_text = text.lower()
    return any(needle.lower() in lower_text for needle in needles)


def _extract_visible_texts(hierarchy: str, *, limit: int = 30) -> list[str]:
    texts: list[str] = []
    for attr in ("text", "content-desc"):
        for value in re.findall(rf'{attr}="([^"]+)"', hierarchy):
            value = value.strip()
            if value and value not in texts:
                texts.append(value)
            if len(texts) >= limit:
                return texts
    return texts


def _is_xhs_album_picker_hierarchy(hierarchy: str) -> bool:
    if "com.xingin.xhs.redscanner:id/" in hierarchy:
        return False
    if not _contains_any_text(hierarchy, ["XhsAlbumActivity", "album.ui.choose", "Album", "相册", "All"]):
        return False
    if not _contains_any_text(hierarchy, ['package="com.xingin.xhs"', "com.xingin.xhs:id/"]):
        return False

    image_nodes = [
        node
        for node in re.findall(r"<node\b[^>]+/>", hierarchy)
        if 'package="com.xingin.xhs"' in node
        and "com.xingin.xhs:id/" in node
        and 'class="android.widget.ImageView"' in node
        and 'clickable="true"' in node
    ]
    grid_nodes = []
    for node in image_nodes:
        bounds = AndroidQrLoginAutomator._node_bounds(node)
        if bounds is None:
            continue
        left, top, right, bottom = bounds
        if top >= 260 and right - left >= 180 and bottom - top >= 180:
            grid_nodes.append(bounds)
    return bool(grid_nodes)
