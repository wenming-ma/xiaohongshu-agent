# Android QR Login Agent Notes

This note records what we have learned about automating Xiaohongshu web QR login with the user's own Android phone and Xiaohongshu app.

## Current Working Route

1. Reuse the shared browser profile first. The current stable browsing domain is `https://www.rednote.com`, backed by `browser-sessions/shared`.
2. For research/search flows, prefer `https://www.rednote.com/explore` and `https://www.rednote.com/search_result?...`. On 2026-05-25, the same shared profile had valid `.rednote.com` login cookies while `www.xiaohongshu.com` redirected to `website-login/error` with `300012 IP at risk`.
3. Only if the shared profile is not logged in, the web side generates a QR login page with Playwright. For login verification, use `https://www.rednote.com/explore`; do not use the Creator Center login page as the validation target.
4. Save the current web page screenshot locally.
5. Push the screenshot to the Android media gallery with ADB.
6. Open Xiaohongshu on Android.
7. Open the side menu from the home page.
8. Tap `Scan`.
9. Tap scanner `Album`.
10. Allow photo/media permission when prompted.
11. Select the newest pushed image from the album picker.
12. Wait for the login confirmation page.
13. Wait for the final `Log in` button countdown to finish.
14. Submit the phone-side login confirmation.
15. Verify the web page separately. Phone-side submission alone is not final success.

## Confirmed UI Anchors

- Package: `com.xingin.xhs`
- Launcher activity observed: `.index.v2.IndexActivityV2`
- Scanner activity observed: `com.xingin.redscanner.scanner.QrCodeScannerActivityV2`
- XHS album activity observed on OPPO: `.v2.album.ui.choose.XhsAlbumActivity`
- Scanner album button resource id: `com.xingin.xhs.redscanner:id/llMyPhoto`
- Home menu content description: `menu`
- Side menu scan entry text: `Scan`
- Confirmation page title: `Login confirmation`
- Countdown button example: `Log in（2）`
- Ready button content description/text: `Log in`
- Scanner invalid-image feedback: `No QR code was identified` and `Click the screen to continue scanning`

## Important Pitfalls

- Do not treat selecting the QR image as success. It only proves the app recognized the QR.
- Do not treat seeing `Log in（2）` as clickable success. It is a countdown state.
- Do not treat clicking `Log in` as web login success. Web side must be checked after phone submission.
- A submitted phone confirmation can still result in `failed login`; this must be a distinct failure state.
- The pushed screenshot currently appears first in the Android album, but the album UI only exposes generic image cells. A dedicated agent should observe the album page before selecting.
- Reusing an old QR screenshot can produce stale or failed-login behavior. The agent should prefer a freshly captured QR image.
- Permissions are device/OS dependent. Samsung Android 12 showed `Allow rednote to access photos and media on your device?`.
- OPPO Android 12 can show a generic permission controller prompt: `"rednote" requires the following permission: Storage` with `com.android.permissioncontroller:id/permission_allow_button`.
- Camera or storage permission prompts can appear between clicking `Scan`/`Album` and seeing the next XHS page. The agent must inspect and allow permission prompts before retrying the next expected action.
- The Xiaohongshu app language can be English or Chinese; tools need both label sets.
- The web browser session is the source of truth for final success.
- A non-QR or stale image can return to the scanner with `No QR code was identified`; this should be a distinct `qr_not_identified` state, not a generic timeout.
- XHS scanner pages also contain `Album` text and clickable `ImageView` chrome. Album-page detection must not rely only on `Album + clickable ImageView`.
- The phone may be left in another app, such as Android Settings or ColorOS Gallery, after manual probing. A dedicated agent should always inspect the current package/activity before choosing the next tool.

## Device Findings

### Samsung

- Serial observed: `RFCMB00H3HY`.
- XHS version observed: `9.31.0`.
- The Samsung route reached XHS scanner, XHS album picker, QR recognition, login confirmation, countdown wait, and final `Log in` click.
- Clicking final `Log in` may still lead to `failed login`; phone-side submission is not success.

### OPPO

- Serial observed: `c62d570e`.
- Model observed: `PEHM00` / OPPO A93 5G.
- ADB and uiautomator2 work after installing the OPPO and Universal ADB drivers.
- XHS home exposes the same `menu`, `Home`, and `Me` anchors as Samsung.
- First scanner/album use can show Android permission controller prompts. The Storage prompt used `permission_allow_button`.
- After storage permission is allowed, tapping scanner `Album` opens XHS internal album activity, not ColorOS Gallery, in the confirmed route.
- A freshly pushed image under `/sdcard/Pictures/xhs-auto-login/` appears as the first image in XHS album after media scan. This was verified with a high-contrast test image.
- Selecting a non-QR test image returns to scanner and shows `No QR code was identified`.
- ColorOS Gallery was observed during earlier manual probing, so the agent should classify `com.coloros.gallery3d` as an out-of-flow state and recover by returning to XHS/scanner.
- Positive validation on 2026-05-25: Playwright opened the web QR page, the screenshot was pushed to OPPO, XHS selected it from album, phone-side confirmation was submitted, and the web page then navigated to `https://www.rednote.com/explore` with the login modal gone. The OPPO app returned to XHS home afterward.
- Stability finding on 2026-05-25: `https://www.rednote.com/explore` and `https://www.rednote.com/search_result?...` worked in the shared profile without a login modal, while `https://www.xiaohongshu.com/explore` and search redirected to `website-login/error` with `error_code=300012`. Research agents should therefore use `rednote.com` for browsing/search.

## Proposed Agent Contract

A dedicated QR login agent should coordinate tools, not run a hardcoded script blindly.

Suggested tool-level actions:

- `capture_web_qr_screenshot`: capture current Playwright page and return path plus page hints.
- `check_rednote_web_login_state`: open Rednote Explore and classify shared browser profile state before attempting a QR login.
- `inspect_android_ui`: return current package, activity, visible texts, and classified Android state as JSON.
- `push_qr_to_android_gallery`: ADB push and media scan a QR image.
- `open_xhs_scanner`: navigate Xiaohongshu home/menu/scanner and handle Android permission prompts.
- `open_scanner_album`: tap scanner album and handle Android permission prompts.
- `select_latest_album_image`: select the first large image cell in the XHS album picker.
- `submit_xhs_login_confirmation`: wait out countdown and submit only a ready confirmation button.
- `classify_android_login_state`: return states such as `scanner_ready`, `album_picker`, `android_permission`, `confirmation_countdown`, `confirmation_ready`, `confirmation_submitted`, `login_failed`, `qr_expired`, `qr_not_identified`, `coloros_gallery`, `unknown`.
- `verify_web_login_state`: check Playwright page/session after phone-side submission.

The agent should use the Android state after every action and choose the next tool call from state, instead of assuming the previous click worked.

The current implementation exposes the Android-side subset through `AndroidQrLoginToolset`:

- `inspect_android_ui()`
- `push_qr_to_android_gallery(image_path)`
- `open_xhs_scanner()`
- `open_scanner_album()`
- `select_latest_album_image()`
- `submit_xhs_login_confirmation()`

Each tool returns JSON so a dedicated logging/login agent can inspect `state`, `package`, `activity`, and `visible_texts` before choosing the next action.

## Status Values

- `disabled`: automation disabled by env.
- `missing_image`: local QR image path missing.
- `adb_error`: failed to push or media-scan image.
- `uiautomator_unavailable`: device unavailable or uiautomator2 cannot connect.
- `scan_entry_not_found`: Xiaohongshu did not expose a scan entry.
- `album_entry_not_found`: scanner opened but album entry was not found.
- `album_image_not_found`: album picker opened but no selectable image was found.
- `qr_expired`: app recognized an expired QR code.
- `qr_not_identified`: app selected an album image but did not identify a QR code.
- `android_permission`: Android permission controller prompt is visible and should be handled before continuing.
- `coloros_gallery`: OPPO system gallery is visible; return to the XHS scanner flow before selecting an album image.
- `login_failed`: app reported failed login after confirmation.
- `confirmation_not_found`: QR was selected but no confirmation page/button was found.
- `confirmation_submitted`: phone-side confirmation was submitted; web-side verification is still required.
- `web_login_verified`: future agent-level state after Playwright confirms login.

## Environment Knobs

- `XHS_ANDROID_QR_ENABLED`: default true.
- `ANDROID_SERIAL` or `XHS_ANDROID_SERIAL`: target ADB device serial.
- `XHS_ANDROID_XHS_PACKAGE`: default `com.xingin.xhs`.
- `XHS_ANDROID_QR_REMOTE_DIR`: default `/sdcard/Pictures/xhs-auto-login`.
