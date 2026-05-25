from pathlib import Path
import json

from src.agents.shared.login.android_qr import (
    AndroidQrLoginAutomator,
    AndroidQrLoginConfig,
    AndroidQrLoginToolset,
    build_android_qr_tool_message,
    classify_android_login_hierarchy,
)


def test_android_qr_config_is_enabled_by_default_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("XHS_ANDROID_QR_ENABLED", raising=False)
    assert AndroidQrLoginConfig.from_env().enabled is True

    monkeypatch.setenv("XHS_ANDROID_QR_ENABLED", "false")
    assert AndroidQrLoginConfig.from_env().enabled is False


def test_push_image_to_gallery_uses_serial_and_refreshes_media(tmp_path: Path):
    image = tmp_path / "login page.png"
    image.write_bytes(b"png")
    calls: list[list[str]] = []

    def fake_runner(args: list[str]) -> str:
        calls.append(args)
        return ""

    config = AndroidQrLoginConfig(serial="RFCMB00H3HY")
    automator = AndroidQrLoginAutomator(config=config, adb_runner=fake_runner)

    remote = automator.push_image_to_gallery(image)

    assert remote == "/sdcard/Pictures/xhs-auto-login/login_page.png"
    assert calls == [
        [
            "adb",
            "-s",
            "RFCMB00H3HY",
            "shell",
            "mkdir",
            "-p",
            "/sdcard/Pictures/xhs-auto-login",
        ],
        [
            "adb",
            "-s",
            "RFCMB00H3HY",
            "push",
            str(image),
            "/sdcard/Pictures/xhs-auto-login/login_page.png",
        ],
        [
            "adb",
            "-s",
            "RFCMB00H3HY",
            "shell",
            "am",
            "broadcast",
            "-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
            "-d",
            "file:///sdcard/Pictures/xhs-auto-login/login_page.png",
        ],
    ]


def test_attempt_scan_returns_disabled_without_touching_adb(tmp_path: Path):
    image = tmp_path / "qr.png"
    image.write_bytes(b"png")
    calls: list[list[str]] = []

    config = AndroidQrLoginConfig(enabled=False)
    automator = AndroidQrLoginAutomator(config=config, adb_runner=lambda args: calls.append(args) or "")

    result = automator.attempt_scan_from_album(image)

    assert result.success is False
    assert result.status == "disabled"
    assert calls == []


class _FakeXpath:
    def __init__(self, device: "_FakeDevice", query: str):
        self.device = device
        self.query = query

    @property
    def exists(self) -> bool:
        return self.device.exists_xpath(self.query)

    def click(self) -> None:
        self.device.click_xpath(self.query)


class _FakeSelector:
    def __init__(self, device: "_FakeDevice", selector: dict[str, str]):
        self.device = device
        self.selector = selector

    @property
    def exists(self) -> bool:
        return self.device.exists_selector(self.selector)

    def click(self) -> None:
        self.device.click_selector(self.selector)


class _FakeDevice:
    info = {"displayWidth": 1440, "displayHeight": 3040}

    def __init__(self) -> None:
        self.stage = "home"
        self.calls: list[tuple] = []

    def screen_on(self) -> None:
        self.calls.append(("screen_on",))

    def app_start(self, package_name: str, stop: bool = False) -> None:
        self.calls.append(("app_start", package_name, stop))

    def sleep(self, seconds: float) -> None:
        self.calls.append(("sleep", seconds))

    def xpath(self, query: str) -> _FakeXpath:
        return _FakeXpath(self, query)

    def __call__(self, **selector: str) -> _FakeSelector:
        return _FakeSelector(self, selector)

    def click(self, x: int, y: int) -> None:
        self.calls.append(("coord", x, y, self.stage))
        if self.stage == "home":
            self.stage = "menu"
        elif self.stage == "album":
            self.stage = "confirmation"

    def dump_hierarchy(self, compressed: bool = False) -> str:
        if self.stage == "home":
            return '<hierarchy><node content-desc="menu" clickable="true" bounds="[32,128][158,254]" /></hierarchy>'
        if self.stage == "menu":
            return '<hierarchy><node text="Scan" clickable="true" bounds="[50,2500][250,2700]" /></hierarchy>'
        if self.stage == "scanner":
            return (
                '<hierarchy><node text="Album" resource-id="com.xingin.xhs.redscanner:id/llMyPhoto" '
                'clickable="true" bounds="[1050,2460][1340,2730]" /></hierarchy>'
            )
        if self.stage == "permission":
            return (
                '<hierarchy><node text="Allow" '
                'resource-id="com.android.permissioncontroller:id/permission_allow_button" '
                'clickable="true" bounds="[85,2438][1355,2564]" /></hierarchy>'
            )
        if self.stage == "album":
            return (
                '<hierarchy><node text="All" package="com.xingin.xhs" />'
                '<node text="" package="com.xingin.xhs" '
                'resource-id="com.xingin.xhs:id/0_resource_name_obfuscated" '
                'class="android.widget.ImageView" clickable="true" bounds="[0,328][357,688]" /></hierarchy>'
            )
        if self.stage == "confirmation":
            if self.calls.count(("sleep", 1.0)) >= 3:
                return (
                    '<hierarchy><node text="Login confirmation" />'
                    '<node text="Log in to rednote desktop" />'
                    '<node content-desc="Log in" clickable="true" bounds="[168,2365][1272,2533]" /></hierarchy>'
                )
            return (
                '<hierarchy><node text="Login confirmation" />'
                '<node text="Log in to rednote desktop" />'
                '<node content-desc="Log in（2）" clickable="true" bounds="[168,2365][1272,2533]" /></hierarchy>'
            )
        if self.stage == "logged_in":
            return '<hierarchy><node text="Home" /></hierarchy>'
        return "<hierarchy />"

    def exists_xpath(self, query: str) -> bool:
        xml = self.dump_hierarchy()
        if "menu" in query:
            return self.stage == "home" and "menu" in xml
        if "Scan" in query:
            return self.stage == "menu" and "Scan" in xml
        if "Log in" in query or "登录" in query:
            return self.stage == "confirmation"
        return False

    def click_xpath(self, query: str) -> None:
        self.calls.append(("xpath", query, self.stage))
        if self.stage == "home" and "menu" in query:
            self.stage = "menu"
        elif self.stage == "menu" and "Scan" in query:
            self.stage = "scanner"
        elif self.stage == "confirmation" and ("Log in" in query or "登录" in query):
            self.stage = "logged_in"

    def exists_selector(self, selector: dict[str, str]) -> bool:
        resource_id = selector.get("resourceId")
        text = selector.get("text")
        if self.stage == "scanner" and resource_id == "com.xingin.xhs.redscanner:id/llMyPhoto":
            return True
        if self.stage == "permission" and resource_id == "com.android.permissioncontroller:id/permission_allow_button":
            return True
        if self.stage == "permission" and text == "Allow":
            return True
        return False

    def click_selector(self, selector: dict[str, str]) -> None:
        self.calls.append(("selector", selector, self.stage))
        if self.stage == "scanner":
            self.stage = "permission"
        elif self.stage == "permission":
            self.stage = "album"


def test_probe_xhs_album_scan_clicks_menu_album_photo_and_login():
    device = _FakeDevice()
    automator = AndroidQrLoginAutomator(config=AndroidQrLoginConfig())

    result = automator._probe_xhs_album_scan(device, "/sdcard/Pictures/xhs-auto-login/qr.png")

    assert result.success is False
    assert result.status == "confirmation_submitted"
    assert result.remote_image_path == "/sdcard/Pictures/xhs-auto-login/qr.png"
    assert device.stage == "logged_in"
    assert any(call[0] == "xpath" and call[2] == "home" for call in device.calls)
    assert any(call[0] == "selector" and call[2] == "scanner" for call in device.calls)
    assert any(call[0] == "selector" and call[2] == "permission" for call in device.calls)
    assert any(call[0] == "coord" and call[3] == "album" for call in device.calls)


class _CameraPermissionDevice(_FakeDevice):
    def click_xpath(self, query: str) -> None:
        self.calls.append(("xpath", query, self.stage))
        if self.stage == "home" and "menu" in query:
            self.stage = "menu"
        elif self.stage == "menu" and "Scan" in query:
            self.stage = "camera_permission"

    def dump_hierarchy(self, compressed: bool = False) -> str:
        if self.stage == "camera_permission":
            return (
                '<hierarchy><node text="Allow" '
                'resource-id="com.android.permissioncontroller:id/permission_allow_button" '
                'clickable="true" bounds="[60,1288][1020,1438]" /></hierarchy>'
            )
        return super().dump_hierarchy(compressed=compressed)

    def exists_selector(self, selector: dict[str, str]) -> bool:
        resource_id = selector.get("resourceId")
        text = selector.get("text")
        if self.stage == "camera_permission" and resource_id == "com.android.permissioncontroller:id/permission_allow_button":
            return True
        if self.stage == "camera_permission" and text == "Allow":
            return True
        return super().exists_selector(selector)

    def click_selector(self, selector: dict[str, str]) -> None:
        self.calls.append(("selector", selector, self.stage))
        if self.stage == "camera_permission":
            self.stage = "scanner"
            return
        super().click_selector(selector)


def test_open_scanner_allows_android_permission_prompt():
    device = _CameraPermissionDevice()
    automator = AndroidQrLoginAutomator(config=AndroidQrLoginConfig(ui_wait_seconds=2))

    assert automator._open_scanner(device) is True

    assert device.stage == "scanner"
    assert any(call[0] == "selector" and call[2] == "camera_permission" for call in device.calls)


class _NoQrAfterAlbumDevice(_FakeDevice):
    def dump_hierarchy(self, compressed: bool = False) -> str:
        if self.stage == "confirmation":
            return (
                '<hierarchy><node text="Scan QR code" />'
                '<node text="No QR code was identified" />'
                '<node text="Click the screen to continue scanning" />'
                '<node text="Album" resource-id="com.xingin.xhs.redscanner:id/llMyPhoto" /></hierarchy>'
            )
        return super().dump_hierarchy(compressed=compressed)


def test_probe_xhs_album_scan_reports_unidentified_qr():
    device = _NoQrAfterAlbumDevice()
    automator = AndroidQrLoginAutomator(config=AndroidQrLoginConfig(ui_wait_seconds=2))

    result = automator._probe_xhs_album_scan(device, "/sdcard/Pictures/xhs-auto-login/not-a-qr.png")

    assert result.success is False
    assert result.status == "qr_not_identified"


class _CountdownConfirmationDevice:
    def __init__(self) -> None:
        self.polls = 0
        self.clicked = False
        self.done = False

    def dump_hierarchy(self, compressed: bool = False) -> str:
        if self.done:
            return '<hierarchy><node text="Home" /></hierarchy>'
        self.polls += 1
        label = "Log in（2）" if self.polls < 3 else "Log in"
        return (
            '<hierarchy><node text="Login confirmation" />'
            '<node text="Log in to rednote desktop" />'
            f'<node content-desc="{label}" clickable="true" bounds="[168,2365][1272,2533]" /></hierarchy>'
        )

    def xpath(self, query: str) -> _FakeXpath:
        return _FakeXpath(self, query)

    def exists_xpath(self, query: str) -> bool:
        return "Log in" in query and self.polls >= 3

    def click_xpath(self, query: str) -> None:
        self.clicked = True
        self.done = True

    def sleep(self, seconds: float) -> None:
        pass


def test_tap_login_confirmation_waits_for_countdown_button():
    device = _CountdownConfirmationDevice()
    automator = AndroidQrLoginAutomator(config=AndroidQrLoginConfig())

    assert automator._tap_login_confirmation(device) == "submitted"

    assert device.clicked is True
    assert device.polls == 3


class _StickyConfirmationDevice:
    def __init__(self) -> None:
        self.clicks = 0
        self.sleeps = 0

    def dump_hierarchy(self, compressed: bool = False) -> str:
        return (
            '<hierarchy><node text="Login confirmation" />'
            '<node text="Log in to rednote desktop" />'
            '<node content-desc="Log in" clickable="true" bounds="[168,2365][1272,2533]" /></hierarchy>'
        )

    def xpath(self, query: str) -> _FakeXpath:
        return _FakeXpath(self, query)

    def exists_xpath(self, query: str) -> bool:
        return "Log in" in query

    def click_xpath(self, query: str) -> None:
        self.clicks += 1

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1


def test_tap_login_confirmation_requires_page_to_leave_confirmation():
    device = _StickyConfirmationDevice()
    automator = AndroidQrLoginAutomator(config=AndroidQrLoginConfig(ui_wait_seconds=3))

    assert automator._tap_login_confirmation(device) == "not_found"

    assert device.clicks == 1
    assert device.sleeps >= 1


class _FailedLoginDevice:
    def __init__(self) -> None:
        self.stage = "confirmation"

    def dump_hierarchy(self, compressed: bool = False) -> str:
        if self.stage == "failed":
            return '<hierarchy><node text="Failed login" /></hierarchy>'
        return (
            '<hierarchy><node text="Login confirmation" />'
            '<node text="Log in to rednote desktop" />'
            '<node content-desc="Log in" clickable="true" bounds="[168,2365][1272,2533]" /></hierarchy>'
        )

    def xpath(self, query: str) -> _FakeXpath:
        return _FakeXpath(self, query)

    def exists_xpath(self, query: str) -> bool:
        return self.stage == "confirmation" and "Log in" in query

    def click_xpath(self, query: str) -> None:
        self.stage = "failed"

    def sleep(self, seconds: float) -> None:
        pass


def test_tap_login_confirmation_reports_failed_login():
    device = _FailedLoginDevice()
    automator = AndroidQrLoginAutomator(config=AndroidQrLoginConfig(ui_wait_seconds=3))

    result = automator._tap_login_confirmation(device)

    assert result == "login_failed"


def test_classify_android_login_hierarchy_known_states():
    assert classify_android_login_hierarchy('<node text="Failed login" />') == "login_failed"
    assert classify_android_login_hierarchy('<node text="二维码已失效" />') == "qr_expired"
    assert (
        classify_android_login_hierarchy(
            '<node package="com.xingin.xhs" text="No QR code was identified" />'
            '<node package="com.xingin.xhs" text="Click the screen to continue scanning" />'
            '<node package="com.xingin.xhs" text="Album" />'
        )
        == "qr_not_identified"
    )
    assert (
        classify_android_login_hierarchy(
            '<node package="com.android.permissioncontroller" '
            'text="&quot;rednote&quot; requires the following permission: Storage" />'
            '<node package="com.android.permissioncontroller" text="Allow" '
            'resource-id="com.android.permissioncontroller:id/permission_allow_button" />'
        )
        == "android_permission"
    )
    assert classify_android_login_hierarchy('<node package="com.coloros.gallery3d" text="Photos" />') == "coloros_gallery"
    assert (
        classify_android_login_hierarchy(
            '<node text="Login confirmation" /><node content-desc="Log in（2）" />'
        )
        == "confirmation_countdown"
    )
    assert (
        classify_android_login_hierarchy(
            '<node text="Login confirmation" /><node content-desc="Log in" clickable="true" />'
        )
        == "confirmation_ready"
    )
    assert (
        classify_android_login_hierarchy(
            '<node resource-id="com.xingin.xhs.redscanner:id/llMyPhoto" text="Album" />'
        )
        == "scanner_ready"
    )
    assert (
        classify_android_login_hierarchy(
            '<node text="Allow rednote to access photos and media on your device?" />'
        )
        == "photo_permission"
    )
    assert (
        classify_android_login_hierarchy(
            '<hierarchy activity="com.xingin.xhs.v2.album.ui.choose.XhsAlbumActivity">'
            '<node package="com.xingin.xhs" resource-id="com.xingin.xhs:id/0_resource_name_obfuscated" '
            'class="android.widget.ImageView" clickable="true" bounds="[0,328][357,688]" />'
            "</hierarchy>"
        )
        == "album_picker"
    )


def test_classify_android_login_hierarchy_does_not_treat_settings_images_as_album():
    hierarchy = (
        '<node package="com.android.settings" class="android.widget.ImageView" '
        'clickable="true" bounds="[0,328][357,688]" />'
    )

    assert classify_android_login_hierarchy(hierarchy) == "unknown"


def test_classify_android_login_hierarchy_does_not_treat_xhs_dialog_image_as_album():
    hierarchy = (
        '<node package="com.xingin.xhs" text="打开通知，有热门笔记和互动消息第一时间通知你" />'
        '<node package="com.xingin.xhs" class="android.widget.ImageView" clickable="true" '
        'bounds="[847,865][937,955]" />'
    )

    assert classify_android_login_hierarchy(hierarchy) == "startup_dialog"


def test_classify_android_login_hierarchy_does_not_treat_xhs_home_feed_as_album():
    hierarchy = (
        '<node package="com.xingin.xhs" content-desc="menu" clickable="true" />'
        '<node package="com.xingin.xhs" content-desc="Home" clickable="true" />'
        '<node package="com.xingin.xhs" class="android.widget.ImageView" clickable="true" '
        'bounds="[15,362][533,1307]" />'
    )

    assert classify_android_login_hierarchy(hierarchy) == "xhs_home"


def test_classify_android_login_hierarchy_does_not_treat_scanner_chrome_as_album():
    hierarchy = (
        '<node package="com.xingin.xhs" text="" resource-id="com.xingin.xhs.redscanner:id/ivBack" '
        'class="android.widget.ImageView" clickable="true" bounds="[0,110][132,242]" />'
        '<node package="com.xingin.xhs" text="Album" class="android.widget.TextView" '
        'clickable="false" bounds="[793,2148][887,2186]" />'
        '<node package="com.xingin.xhs" text="" resource-id="com.xingin.xhs.redscanner:id/llMyPhoto" '
        'class="android.widget.LinearLayout" clickable="true" bounds="[750,1938][930,2186]" />'
    )

    assert classify_android_login_hierarchy(hierarchy) == "scanner_ready"


def test_build_android_qr_tool_message_describes_success():
    result = build_android_qr_tool_message(
        success=True,
        status="web_login_verified",
        message="The web page is logged in.",
        screenshot_path=Path("C:/tmp/login.png"),
        remote_image_path="/sdcard/Pictures/xhs-auto-login/login.png",
    )

    assert "Android 自动扫码成功" in result
    assert "web_login_verified" in result
    assert "刷新或检查当前网页登录状态" in result


def test_build_android_qr_tool_message_describes_submitted_confirmation():
    result = build_android_qr_tool_message(
        success=False,
        status="confirmation_submitted",
        message="Xiaohongshu QR image was selected from Album and the login confirmation was submitted.",
        screenshot_path=Path("C:/tmp/login.png"),
        remote_image_path="/sdcard/Pictures/xhs-auto-login/login.png",
    )

    assert "Android 已提交登录确认" in result
    assert "检查当前网页登录状态" in result


def test_build_android_qr_tool_message_describes_fallback():
    result = build_android_qr_tool_message(
        success=False,
        status="scan_entry_not_found",
        message="Launched Xiaohongshu, but the scan entry was not found.",
        screenshot_path=Path("C:/tmp/login.png"),
        remote_image_path="/sdcard/Pictures/xhs-auto-login/login.png",
    )

    assert "Android 自动扫码未完成" in result
    assert "返回结构化失败" in result


class _ToolDevice(_FakeDevice):
    def app_current(self) -> dict[str, str]:
        if self.stage == "scanner":
            return {
                "package": "com.xingin.xhs",
                "activity": "com.xingin.redscanner.scanner.QrCodeScannerActivityV2",
            }
        if self.stage == "album":
            return {"package": "com.xingin.xhs", "activity": ".v2.album.ui.choose.XhsAlbumActivity"}
        return {"package": "com.xingin.xhs", "activity": ".index.v2.IndexActivityV2"}


class _ToolAutomator(AndroidQrLoginAutomator):
    def __init__(self, device: _ToolDevice):
        super().__init__(config=AndroidQrLoginConfig(ui_wait_seconds=2))
        self.device = device

    def _connect_uiautomator(self):
        return self.device


def test_android_qr_toolset_inspects_android_ui_as_json():
    device = _ToolDevice()
    device.stage = "scanner"
    toolset = AndroidQrLoginToolset(_ToolAutomator(device))

    payload = json.loads(toolset.inspect_android_ui())

    assert payload["ok"] is True
    assert payload["state"] == "scanner_ready"
    assert payload["package"] == "com.xingin.xhs"
    assert payload["activity"] == "com.xingin.redscanner.scanner.QrCodeScannerActivityV2"
    assert "Album" in payload["visible_texts"]


def test_android_qr_toolset_exposes_small_stateful_actions():
    device = _ToolDevice()
    device.stage = "scanner"
    toolset = AndroidQrLoginToolset(_ToolAutomator(device))

    open_album = json.loads(toolset.open_scanner_album())
    assert open_album["ok"] is True
    assert open_album["state"] == "album_picker"

    select_image = json.loads(toolset.select_latest_album_image())
    assert select_image["ok"] is True
    assert select_image["state"] in {"confirmation_countdown", "confirmation_ready"}
