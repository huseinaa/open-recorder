"""The Windows calls no Python library wraps cleanly. Everything that talks to the OS directly
through ctypes lives here and nowhere else."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import threading
import time
import winreg
import winsound
from typing import Callable

from .logs import log

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004 and newer
ERROR_ALREADY_EXISTS = 183
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000


def set_dpi_aware() -> None:
    """Real pixels, so a 300 px bubble is 300 px on the recording at any display scale."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:
        pass


def windows_build() -> int:
    return sys.getwindowsversion().build


def hide_from_capture(window) -> None:
    """Hide a Tk window from every screen capture (ffmpeg, OBS, Teams, screenshots), while it
    stays visible on the monitor."""
    window.update_idletasks()
    if not user32.SetWindowDisplayAffinity(int(window.wm_frame(), 16), WDA_EXCLUDEFROMCAPTURE):
        log.warning("could not hide a window from capture (Windows 10 2004 or newer is needed)")


def interrupt_time() -> float:
    """The clock DirectShow stamps camera frames with (Windows interrupt time, in seconds)."""
    v = ctypes.c_ulonglong()
    ctypes.WinDLL("KernelBase").QueryInterruptTimePrecise(ctypes.byref(v))
    return v.value / 1e7


def single_instance(name: str):
    """A named mutex. Returns its handle, or None when another copy is already running."""
    handle = kernel32.CreateMutexW(None, False, name)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def release(handle) -> None:
    if handle:
        kernel32.CloseHandle(handle)


ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x1, 0x2


def wake_display() -> None:
    """Turn a sleeping display back on: a monitor that is off cannot be captured."""
    kernel32.SetThreadExecutionState(ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED)


def keep_awake(on: bool) -> None:
    """While recording, stop Windows from turning the screen off or sleeping when nobody touches
    the mouse (a long stretch of talking). Applies to the calling thread: call it from the UI thread."""
    kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_DISPLAY_REQUIRED | ES_SYSTEM_REQUIRED if on else 0))


def set_gpu_preference(exe, pref: int) -> None:
    """Windows' per-app graphics setting. pref 1 = power saving (integrated chip), 2 = high
    performance (dedicated chip). Per user, no admin needed."""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\DirectX\UserGpuPreferences") as k:
            try:
                current = winreg.QueryValueEx(k, str(exe))[0]
            except FileNotFoundError:
                current = None
            if current != f"GpuPreference={pref};":
                winreg.SetValueEx(k, str(exe), 0, winreg.REG_SZ, f"GpuPreference={pref};")
                log.info(f"set {exe} to GPU preference {pref} (was {current})")
    except OSError as e:
        log.warning(f"could not set the GPU preference of {exe}: {e!r}")


# ---------- sounds ----------
BEEP_START = ((1320, 140),)
BEEP_STOP = ((660, 120), (0, 60), (660, 120))
BEEP_ALARM = ((1760, 90), (0, 60), (1760, 90), (0, 60), (1760, 90))


def beep(*notes) -> None:
    def play():
        for freq, ms in notes:
            winsound.Beep(freq, ms) if freq else time.sleep(ms / 1000)
    threading.Thread(target=play, daemon=True).start()


# ---------- global hotkeys ----------
_MODS = {"ctrl": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}
_KEYS = {**{f"f{i}": 0x6F + i for i in range(1, 13)}, "space": 0x20, "home": 0x24, "end": 0x23}


def parse_hotkey(text: str) -> tuple[int, int | None]:
    mods, vk = MOD_NOREPEAT, None
    for part in text.lower().replace(" ", "").split("+"):
        if part in _MODS:
            mods |= _MODS[part]
        elif part in _KEYS:
            vk = _KEYS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
    return mods, vk


def start_hotkeys(bindings: dict[str, str], callback: Callable[[str], None]) -> None:
    """Register system-wide hotkeys ({name: "ctrl+alt+r"}) and call callback(name) from a
    background thread when one is pressed. RegisterHotKey reserves the key for this app, so it
    works while any other window has focus."""
    names = dict(enumerate(bindings, start=1))

    def loop():
        for hk_id, name in names.items():
            mods, vk = parse_hotkey(bindings[name])
            if vk is None or not user32.RegisterHotKey(None, hk_id, mods, vk):
                log.warning(f"hotkey {bindings[name]} could not be registered (taken by another app?)")
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in names:
                callback(names[msg.wParam])
    threading.Thread(target=loop, daemon=True).start()


class _SHFileOp(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("wFunc", wt.UINT), ("pFrom", wt.LPCWSTR), ("pTo", wt.LPCWSTR),
                ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wt.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wt.LPCWSTR)]


def recycle(path) -> None:
    """Send a file or folder to the Recycle Bin, with no Windows dialog. Raises OSError if it
    could not (a file in it is open somewhere, for example)."""
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = _SHFileOp(None, FO_DELETE, str(path) + "\0", None,  # the list ends with a second NUL
                   FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI, False, None, None)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code or op.fAnyOperationsAborted:
        raise OSError(f"Windows could not move it to the Recycle Bin (code {code})")
