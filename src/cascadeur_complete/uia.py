from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


class UIAutomationError(RuntimeError):
    def __init__(self, message: str, *, not_running: bool = False, timed_out: bool = False):
        super().__init__(message)
        self.not_running = not_running
        self.timed_out = timed_out


@dataclass(frozen=True)
class TriggerEvidence:
    window_title: str
    menu_path: tuple[str, ...]
    automation_id: str
    invoked_at: float


@dataclass(frozen=True)
class ModalEvidence:
    window_title: str
    button: str
    dismissed_at: float


@dataclass(frozen=True)
class FileDialogEvidence:
    action_id: str
    options_title: str | None
    dialog_title: str
    file_name_automation_id: str
    accept_automation_id: str
    file_type: str | None
    completed_at: float


_CASCADEUR_HANDLE: int | None = None
_PROCESS_PENDING_POINTS: tuple[int, tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]] | None = None


def _is_cascadeur_window_title(title: str) -> bool:
    normalized = title.strip().casefold()
    return normalized == "cascadeur" or normalized.endswith(" - cascadeur")


def _native_cascadeur_handles() -> list[int]:
    """Find visible Cascadeur top-level windows without scanning the UIA tree."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
    except (AttributeError, ImportError):  # pragma: no cover - Windows runtime path
        return []

    handles: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def collect(handle, _lparam):
        if not user32.IsWindowVisible(handle):
            return True
        length = user32.GetWindowTextLengthW(handle)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, length + 1)
        if _is_cascadeur_window_title(buffer.value):
            handles.append(int(handle))
        return True

    user32.EnumWindows(collect, 0)
    return handles


def _native_window_title(handle: int) -> str:
    import ctypes

    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(handle)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(handle, buffer, length + 1)
    return buffer.value


def cascadeur_window_titles() -> list[str]:
    """Return visible Cascadeur window titles using only bounded Win32 calls."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
    except (AttributeError, ImportError):  # pragma: no cover - Windows runtime path
        return []
    titles = []
    for handle in _native_cascadeur_handles():
        length = user32.GetWindowTextLengthW(handle)
        if length <= 0:
            continue
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(handle, buffer, length + 1)
        if _is_cascadeur_window_title(buffer.value):
            titles.append(buffer.value)
    return titles


def _active_tab_span(pixels: list[tuple[int, int, int]]) -> tuple[int, int] | None:
    """Locate Cascadeur 2026.1's active scene-tab background in a screen row."""
    indices = [index for index, (red, green, blue) in enumerate(pixels) if red == green == blue and 56 <= red <= 64]
    if not indices:
        return None
    clusters: list[list[int]] = [[indices[0]]]
    for index in indices[1:]:
        if index - clusters[-1][-1] > 45:
            clusters.append([index])
        else:
            clusters[-1].append(index)
    candidates = [cluster for cluster in clusters if cluster[-1] - cluster[0] >= 80 and len(cluster) >= 35]
    if not candidates:
        return None
    selected = max(candidates, key=lambda cluster: (len(cluster), cluster[-1] - cluster[0]))
    return selected[0], selected[-1]


def _capture_screen_row(left: int, top: int, width: int) -> list[tuple[int, int, int]]:
    """Capture one BGRA screen row with GDI, avoiding a Pillow dependency."""
    import ctypes
    from ctypes import wintypes

    class BitmapInfoHeader(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BitmapInfo(ctypes.Structure):
        _fields_ = [("bmiHeader", BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    handle_type = ctypes.c_void_p
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = handle_type
    user32.ReleaseDC.argtypes = [wintypes.HWND, handle_type]
    gdi32.CreateCompatibleDC.argtypes = [handle_type]
    gdi32.CreateCompatibleDC.restype = handle_type
    gdi32.CreateCompatibleBitmap.argtypes = [handle_type, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = handle_type
    gdi32.SelectObject.argtypes = [handle_type, handle_type]
    gdi32.SelectObject.restype = handle_type
    gdi32.BitBlt.argtypes = [
        handle_type,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        handle_type,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
    ]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        handle_type,
        handle_type,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(BitmapInfo),
        wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [handle_type]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [handle_type]
    gdi32.DeleteDC.restype = wintypes.BOOL
    screen_dc = user32.GetDC(0)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, 1)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    buffer = (ctypes.c_ubyte * (width * 4))()
    info = BitmapInfo()
    info.bmiHeader.biSize = ctypes.sizeof(BitmapInfoHeader)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -1
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    try:
        if not gdi32.BitBlt(memory_dc, 0, 0, width, 1, screen_dc, left, top, 0x00CC0020):
            return []
        if not gdi32.GetDIBits(memory_dc, bitmap, 0, 1, buffer, ctypes.byref(info), 0):
            return []
        return [(buffer[offset + 2], buffer[offset + 1], buffer[offset]) for offset in range(0, width * 4, 4)]
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)


def _scene_tab_nudge_points(wrapper) -> tuple[tuple[int, int], tuple[int, int]] | None:
    rectangle = wrapper.rectangle()
    left = max(0, int(rectangle.left))
    width = max(1, min(int(rectangle.width() * 0.72), int(rectangle.right) - left))
    row_y = max(0, int(rectangle.top + 111))
    span = _active_tab_span(_capture_screen_row(left, row_y, width))
    if span is None:
        return None
    active_left, active_right = left + span[0], left + span[1]
    active_point = ((active_left + active_right) // 2, row_y)
    if active_left - left > 120:
        alternate_point = (active_left - 80, row_y)
    else:
        alternate_point = (min(left + width - 20, active_right + 80), row_y)
    return alternate_point, active_point


def _all_queued_requests_are_scene_bound() -> bool:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return False
    paths = sorted((Path(local) / "CascadeurMCP" / "cascadeur-complete" / "state" / "requests").glob("*.json"))
    if not paths:
        return False
    try:
        return all(bool(json.loads(path.read_text(encoding="utf-8")).get("scene_id")) for path in paths)
    except (OSError, ValueError, TypeError):
        return False


def _has_unclaimed_requests() -> bool:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return False
    return any((Path(local) / "CascadeurMCP" / "cascadeur-complete" / "state" / "requests").glob("*.json"))


def _queued_request_scene_ids() -> set[str]:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return set()
    result: set[str] = set()
    root = Path(local) / "CascadeurMCP" / "cascadeur-complete" / "state" / "requests"
    for path in root.glob("*.json"):
        with suppress(OSError, ValueError, TypeError):
            scene_id = json.loads(path.read_text(encoding="utf-8")).get("scene_id")
            if scene_id:
                result.add(str(scene_id))
    return result


def _scene_id_from_window_title(title: str) -> str | None:
    suffix = " - Cascadeur"
    if not title.endswith(suffix):
        return None
    path_or_name = title[: -len(suffix)]
    return hashlib.sha256(path_or_name.encode("utf-8")).hexdigest()[:24] if path_or_name else None


def invoke_process_pending() -> TriggerEvidence:
    """Invoke Commands > Cascadeur Complete > Process Pending through UI Automation."""
    try:
        from pywinauto import Desktop
    except ImportError as exc:  # pragma: no cover - dependency check
        raise UIAutomationError("pywinauto is not installed") from exc

    global _CASCADEUR_HANDLE, _PROCESS_PENDING_POINTS
    desktop = Desktop(backend="uia")
    native_desktop = Desktop(backend="win32")
    wrapper = None
    if _CASCADEUR_HANDLE is not None:
        cached = native_desktop.window(handle=_CASCADEUR_HANDLE)
        if cached.exists(timeout=0.1, retry_interval=0.05):
            with suppress(Exception):
                wrapper = cached.wrapper_object()
    if wrapper is None:
        candidates = []
        for handle in _native_cascadeur_handles():
            with suppress(Exception):
                candidates.append(native_desktop.window(handle=handle).wrapper_object())
        if not candidates:
            raise UIAutomationError("No visible Cascadeur window", not_running=True)
        wrapper = max(candidates, key=lambda item: item.rectangle().width() * item.rectangle().height())
        _CASCADEUR_HANDLE = int(wrapper.handle)
        if _PROCESS_PENDING_POINTS and _PROCESS_PENDING_POINTS[0] != _CASCADEUR_HANDLE:
            _PROCESS_PENDING_POINTS = None
    window_spec = desktop.window(handle=wrapper.handle)
    process_pending_id = "Commands.Cascadeur Complete.Process Pending"

    def activate_foreground():
        """Make physical menu clicks safe in the presence of overlapping windows."""
        import ctypes

        user32 = ctypes.windll.user32
        handle = int(wrapper.handle)
        for _attempt in range(3):
            user32.ShowWindow(handle, 9)  # SW_RESTORE
            user32.BringWindowToTop(handle)
            user32.SetForegroundWindow(handle)
            # Windows reports the foreground handle before the compositor and
            # Qt input routing have fully settled. A short stabilization delay
            # prevents the subsequent physical menu click from landing on the
            # previously focused Codex window.
            time.sleep(0.5)
            if int(user32.GetForegroundWindow()) == handle:
                return
        raise UIAutomationError("Cascadeur could not become the foreground window")

    def native_click(point: tuple[int, int]) -> None:
        """Send a physical click that Cascadeur's QML menu reliably accepts."""
        import ctypes

        user32 = ctypes.windll.user32
        user32.SetCursorPos(*point)
        time.sleep(0.15)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
        time.sleep(0.1)
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP

    activate_foreground()

    def center(item):
        rectangle = item.rectangle()
        return (
            int((rectangle.left + rectangle.right) / 2),
            int((rectangle.top + rectangle.bottom) / 2),
        )

    def exact_visible(spec, identity: str, timeout: float):
        if not spec.exists(timeout=timeout, retry_interval=0.05):
            raise UIAutomationError(f"Menu item did not appear: {identity}")
        item = spec.wrapper_object()
        if not item.is_visible():
            raise UIAutomationError(f"Menu item is not visible: {identity}")
        return item

    try:
        # Popup descendants in Cascadeur 2026.1's QML accessibility provider
        # can block UIA indefinitely. The stable MenuBar headings remain safe
        # to query. From the verified Commands heading, use version-pinned,
        # DPI-scaled popup offsets and let the bridge response provide the
        # definitive postcondition that Process Pending actually ran.
        if _PROCESS_PENDING_POINTS and _PROCESS_PENDING_POINTS[0] == int(wrapper.handle):
            _, neutral_point, commands_point, group_point, pending_point = _PROCESS_PENDING_POINTS
        else:
            commands = exact_visible(window_spec.child_window(title="Commands"), "Commands", 1.5)
            window_rect = wrapper.rectangle()
            # Maximized Qt windows report an eight-pixel negative resize
            # border.  Eighteen pixels from that rectangle maps to screen y=10,
            # a stable title-bar point; y=2 is still in the non-client border
            # and intermittently failed to dismiss the previous popup.
            neutral_point = (int((window_rect.left + window_rect.right) / 2), int(window_rect.top + 18))
            commands_point = center(commands)
            commands_rect = commands.rectangle()
            scale = max(0.5, commands_rect.height() / 28.0)
            popup_y = int(commands_rect.bottom + (55 * scale))
            group_point = (int(commands_rect.left + (112 * scale)), popup_y)
            pending_point = (int(group_point[0] + (181 * scale)), popup_y)
            _PROCESS_PENDING_POINTS = (
                int(wrapper.handle),
                neutral_point,
                commands_point,
                group_point,
                pending_point,
            )
        event_nudged = False
        target_scene_ids = _queued_request_scene_ids()
        if len(target_scene_ids) == 1:
            # Cycle exactly one tab with a native Ctrl+Tab chord. The
            # scene_activated bridge handler claims only requests matching the
            # newly active scene; repeated idempotent dispatches walk all open
            # tabs without ever executing on the wrong document. Cycling even
            # when the target is currently visible avoids relying on the QML
            # submenu for normal scene-bound traffic.
            import ctypes

            user32 = ctypes.windll.user32
            user32.keybd_event(0x11, 0, 0, 0)  # VK_CONTROL down
            user32.keybd_event(0x09, 0, 0, 0)  # VK_TAB down
            user32.keybd_event(0x09, 0, 0x0002, 0)  # VK_TAB up
            user32.keybd_event(0x11, 0, 0x0002, 0)  # VK_CONTROL up
            time.sleep(1.0)
            event_nudged = True
            if not _has_unclaimed_requests():
                return TriggerEvidence(
                    window_title=_native_window_title(int(wrapper.handle)),
                    menu_path=("Events", "scene_activated", "Cascadeur Complete"),
                    automation_id="Events.scene_activated.queue_drain",
                    invoked_at=time.time(),
                )
            # The command-menu drain applies the same scene-ID filter as the
            # event handler. It is therefore safe to fall through on a single
            # tab (where Ctrl+Tab emits no event) and harmless on a non-target
            # tab (where it leaves the request unclaimed for the next retry).
        if event_nudged and not _has_unclaimed_requests():
            return TriggerEvidence(
                window_title=_native_window_title(int(wrapper.handle)),
                menu_path=("Events", "scene_activated", "Cascadeur Complete"),
                automation_id="Events.scene_activated.queue_drain",
                invoked_at=time.time(),
            )
        # A title-bar click closes any stale QML popup without changing scene
        # selection or canceling an owned modal. Commands can then be opened
        # with one deterministic click instead of toggling an existing popup.
        native_click(neutral_point)
        time.sleep(0.4)
        native_click(commands_point)
        time.sleep(0.8)
        # Cascadeur 2026.1's QML submenu opens on hover. Clicking the group
        # closes the Commands popup and can route the next click to whichever
        # item occupies the same screen point (Poppet on some installations).
        import ctypes

        ctypes.windll.user32.SetCursorPos(*group_point)
        # The submenu animation and Qt input routing can take several frames
        # after the pointer enters the group.  A shorter delay intermittently
        # clicked the viewport before Process Pending became hit-testable.
        time.sleep(2.0)
        native_click(pending_point)
        time.sleep(0.15)
        automation_id = (
            "Events.scene_activated+" + process_pending_id if event_nudged else process_pending_id
        )
    except Exception as exc:
        raise UIAutomationError(f"Cascadeur command menu is unavailable: {exc}") from exc
    return TriggerEvidence(
        window_title=_native_window_title(int(wrapper.handle)),
        menu_path=("Commands", "Cascadeur Complete", "Process Pending"),
        automation_id=automation_id,
        invoked_at=time.time(),
    )


def resolve_autophysics_snap_warning(*, turn_off_single_use_features: bool = True) -> ModalEvidence:
    """Dismiss Cascadeur 2026.1's known post-Snap single-use-feature warning.

    The dialog is accepted only when it is an owned ``Warning`` window with
    both exact ``Yes`` and ``No`` buttons. This avoids treating an unrelated
    warning as an AutoPhysics confirmation.
    """
    try:
        from pywinauto import Desktop
    except ImportError as exc:  # pragma: no cover - dependency check
        raise UIAutomationError("pywinauto is not installed") from exc

    handles = _native_cascadeur_handles()
    if not handles:
        raise UIAutomationError("No visible Cascadeur window", not_running=True)
    desktop = Desktop(backend="uia")
    wrapper = max(
        (desktop.window(handle=handle).wrapper_object() for handle in handles),
        key=lambda item: item.rectangle().width() * item.rectangle().height(),
    )
    warning = desktop.window(handle=wrapper.handle).child_window(title="Warning", control_type="Window")
    if not warning.exists(timeout=1.5, retry_interval=0.05):
        raise UIAutomationError("Expected AutoPhysics Warning dialog is not visible")
    yes = warning.child_window(title="Yes", control_type="Button")
    no = warning.child_window(title="No", control_type="Button")
    if not yes.exists(timeout=0.5, retry_interval=0.05) or not no.exists(timeout=0.5, retry_interval=0.05):
        raise UIAutomationError("AutoPhysics Warning dialog did not expose exact Yes/No buttons")
    button_name = "Yes" if turn_off_single_use_features else "No"
    (yes if turn_off_single_use_features else no).click_input()
    if warning.exists(timeout=2.0, retry_interval=0.05):
        raise UIAutomationError("AutoPhysics Warning dialog did not close after confirmation")
    return ModalEvidence(window_title="Warning", button=button_name, dismissed_at=time.time())


def complete_file_dialog(
    *,
    action_id: str,
    path: str,
    expected_dialog_title: str,
    options_title: str | None = None,
    options_accept_title: str | None = None,
    file_type_extension: str | None = None,
    timeout: float = 20.0,
) -> FileDialogEvidence:
    """Complete one version-pinned Cascadeur 2026.1 file flow.

    Cascadeur exposes native Windows file dialogs as owned UIA ``Window``
    controls.  We accept only the exact expected title and the standard
    filename/accept automation IDs.  Optional QML import/export settings are
    also matched by exact title and button text before the native dialog is
    touched.
    """
    try:
        from pywinauto import Desktop
    except ImportError as exc:  # pragma: no cover - dependency check
        raise UIAutomationError("pywinauto is not installed") from exc

    handles = _native_cascadeur_handles()
    if not handles:
        raise UIAutomationError("No visible Cascadeur window", not_running=True)
    desktop = Desktop(backend="uia")
    owner = max(
        (desktop.window(handle=handle).wrapper_object() for handle in handles),
        key=lambda item: item.rectangle().width() * item.rectangle().height(),
    )
    owner_spec = desktop.window(handle=owner.handle)
    deadline = time.monotonic() + max(1.0, timeout)

    def remaining() -> float:
        return max(0.05, deadline - time.monotonic())

    if options_title:
        options = owner_spec.child_window(title=options_title, control_type="Window")
        if not options.exists(timeout=remaining(), retry_interval=0.05):
            raise UIAutomationError(f"Expected Cascadeur options window did not appear: {options_title}")
        if options.window_text() != options_title:
            raise UIAutomationError(f"Unexpected Cascadeur options window: {options.window_text()}")
        if not options_accept_title:
            raise UIAutomationError("options_accept_title is required for an options window")
        accept_options = options.child_window(title=options_accept_title, control_type="Button")
        if not accept_options.exists(timeout=min(2.0, remaining()), retry_interval=0.05):
            raise UIAutomationError(f"Expected options button did not appear: {options_title} > {options_accept_title}")
        accept_options.click_input()

    dialog = owner_spec.child_window(title=expected_dialog_title, control_type="Window")
    if not dialog.exists(timeout=remaining(), retry_interval=0.05):
        raise UIAutomationError(f"Expected file dialog did not appear: {expected_dialog_title}")
    if dialog.window_text() != expected_dialog_title:
        raise UIAutomationError(f"Unexpected file dialog: {dialog.window_text()}")
    dialog_wrapper = dialog.wrapper_object()
    dialog_rectangle = dialog_wrapper.rectangle()

    def descendant(*, automation_id: str, control_type: str):
        # Native common-dialog controls are separate HWND descendants.  On Qt
        # 6.8, pywinauto can resolve the owned dialog wrapper while returning
        # no children from that wrapper. Search the verified Cascadeur owner
        # tree and then constrain candidates to the exact dialog rectangle.
        matches = [
            item
            for item in owner.descendants(control_type=control_type)
            if (item.element_info.automation_id == automation_id or str(item.control_id()) == automation_id)
            and item.is_visible()
            and item.rectangle().left >= dialog_rectangle.left
            and item.rectangle().right <= dialog_rectangle.right
            and item.rectangle().top >= dialog_rectangle.top
            and item.rectangle().bottom <= dialog_rectangle.bottom
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    filename_candidates = [
        item
        for item in owner.descendants(control_type="Edit")
        if item.element_info.automation_id in {"1001", "1148"}
        and item.is_visible()
        and item.rectangle().left >= dialog_rectangle.left
        and item.rectangle().right <= dialog_rectangle.right
        and item.rectangle().top >= dialog_rectangle.top
        and item.rectangle().bottom <= dialog_rectangle.bottom
    ]
    filename = filename_candidates[0] if len(filename_candidates) == 1 else None
    cancel = descendant(automation_id="2", control_type="Button")
    if filename is None:
        observed = [
            (
                item.element_info.control_type,
                item.element_info.automation_id,
                item.window_text(),
            )
            for item in owner.descendants()
            if item.is_visible()
            and item.rectangle().left >= dialog_rectangle.left
            and item.rectangle().right <= dialog_rectangle.right
            and item.rectangle().top >= dialog_rectangle.top
            and item.rectangle().bottom <= dialog_rectangle.bottom
        ]
        raise UIAutomationError(f"File dialog does not expose one filename Edit ID 1001/1148; observed={observed[:40]}")
    if cancel is None:
        raise UIAutomationError("File dialog does not expose cancel Button ID 2")
    selected_file_type = None
    if file_type_extension:
        extension = file_type_extension.casefold()
        extension_pattern = f"(*{extension})"
        file_type_candidates = [
            item
            for item in owner.descendants(control_type="ComboBox")
            if item.element_info.automation_id in {"1136", "FileTypeControlHost"}
            and item.is_visible()
            and item.rectangle().left >= dialog_rectangle.left
            and item.rectangle().right <= dialog_rectangle.right
            and item.rectangle().top >= dialog_rectangle.top
            and item.rectangle().bottom <= dialog_rectangle.bottom
        ]
        file_type = file_type_candidates[0] if len(file_type_candidates) == 1 else None
        if file_type is None:
            raise UIAutomationError("File dialog does not expose one file type ComboBox ID 1136/FileTypeControlHost")
        selected = str(file_type.selected_text() or "")
        if extension_pattern in selected.casefold():
            selected_file_type = selected
        else:
            file_type.expand()
            time.sleep(0.2)
            matches = [
                item
                for item in owner.descendants(control_type="ListItem")
                if item.is_visible() and extension_pattern in item.window_text().casefold()
            ]
            if len(matches) != 1:
                observed = [
                    item.window_text() for item in owner.descendants(control_type="ListItem") if item.is_visible()
                ]
                file_type.collapse()
                raise UIAutomationError(
                    f"File type {file_type_extension} did not match exactly one visible item: {observed}"
                )
            selected_file_type = matches[0].window_text()
            matches[0].click_input()
    filename_automation_id = str(filename.element_info.automation_id or "1001")
    filename.set_edit_text(path)
    # The Windows 11 Open dialog publishes its ID 1 button only after a valid
    # existing filename has been entered. Resolve it after setting the path.
    accept = descendant(automation_id="1", control_type="Button")
    if accept is None:
        if expected_dialog_title.startswith("Import. preset:"):
            # Windows 11 may keep the Open button out of the UIA tree even
            # after a valid path is entered. Enter invokes the verified
            # dialog's default action without relying on localized text.
            filename.type_keys("{ENTER}")
            accept_automation_id = "ENTER(default action)"
        else:
            buttons = [
                (
                    item.element_info.automation_id,
                    item.control_id(),
                    item.window_text(),
                )
                for item in owner.descendants(control_type="Button")
                if item.is_visible()
                and item.rectangle().left >= dialog_rectangle.left
                and item.rectangle().right <= dialog_rectangle.right
                and item.rectangle().top >= dialog_rectangle.top
                and item.rectangle().bottom <= dialog_rectangle.bottom
            ]
            raise UIAutomationError(f"File dialog does not expose accept Button ID 1; observed_buttons={buttons}")
    else:
        accept.click_input()
        accept_automation_id = "1"
    if dialog.exists(timeout=min(5.0, remaining()), retry_interval=0.05):
        raise UIAutomationError(f"File dialog did not close after accepting path: {expected_dialog_title}")
    return FileDialogEvidence(
        action_id=action_id,
        options_title=options_title,
        dialog_title=expected_dialog_title,
        file_name_automation_id=filename_automation_id,
        accept_automation_id=accept_automation_id,
        file_type=selected_file_type,
        completed_at=time.time(),
    )


def cancel_file_flow(*, expected_dialog_title: str, options_title: str | None = None) -> bool:
    """Best-effort cancellation for an exact file flow after adapter failure."""
    try:
        from pywinauto import Desktop
    except ImportError:  # pragma: no cover - dependency check
        return False
    handles = _native_cascadeur_handles()
    if not handles:
        return False
    desktop = Desktop(backend="uia")
    owner = max(
        (desktop.window(handle=handle).wrapper_object() for handle in handles),
        key=lambda item: item.rectangle().width() * item.rectangle().height(),
    )
    owner_spec = desktop.window(handle=owner.handle)
    canceled = False
    for title in (expected_dialog_title, options_title):
        if not title:
            continue
        window = owner_spec.child_window(title=title, control_type="Window")
        if not window.exists(timeout=0.2, retry_interval=0.05):
            continue
        wrapper = window.wrapper_object()
        cancel = [item for item in wrapper.descendants(control_type="Button") if item.element_info.automation_id == "2"]
        if len(cancel) == 1:
            cancel[0].click_input()
        else:
            wrapper.close()
        canceled = True
    return canceled


def resolve_optional_rig_mode_helper(*, enter_rig_mode: bool = False, timeout: float = 8.0) -> ModalEvidence | None:
    """Resolve the optional post-import Rig Mode Helper using exact buttons."""
    try:
        from pywinauto import Desktop
    except ImportError as exc:  # pragma: no cover - dependency check
        raise UIAutomationError("pywinauto is not installed") from exc
    handles = _native_cascadeur_handles()
    if not handles:
        raise UIAutomationError("No visible Cascadeur window", not_running=True)
    desktop = Desktop(backend="uia")
    owner = max(
        (desktop.window(handle=handle).wrapper_object() for handle in handles),
        key=lambda item: item.rectangle().width() * item.rectangle().height(),
    )
    deadline = time.monotonic() + max(0.1, timeout)
    helper = None
    while time.monotonic() < deadline:
        helper = next(
            (
                item
                for item in owner.descendants(control_type="Window")
                if item.is_visible() and item.window_text().strip().casefold() == "rig mode helper"
            ),
            None,
        )
        if helper is not None:
            break
        time.sleep(0.1)
    if helper is None:
        return None
    yes = [item for item in helper.descendants(control_type="Button") if item.window_text() == "Yes"]
    no = [item for item in helper.descendants(control_type="Button") if item.window_text() == "No"]
    if len(yes) != 1 or len(no) != 1:
        raise UIAutomationError("Rig Mode Helper did not expose exact Yes/No buttons")
    button_name = "Yes" if enter_rig_mode else "No"
    (yes[0] if enter_rig_mode else no[0]).click_input()
    return ModalEvidence(window_title="Rig Mode Helper", button=button_name, dismissed_at=time.time())
