"""Run one process-bound, screenshot-backed Cemu keyboard movement test.

Other Cemu windows remain untouched. Every screenshot and key sequence is
bound to the exact PID/HWND launched by this run, and input is blocked until
that exact HWND is verified in the foreground. Held keys are released in a
finally block. The runner pauses for visual confirmation of the map so it
never assumes that a title-screen click or boot reached the overworld.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import time


if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if sys.platform != 'win32':
    raise SystemExit('Cemu input testing is supported only on Windows.')

import msvcrt

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)

ULONG_PTR = ctypes.c_size_t
WM_CLOSE = 0x0010
SW_RESTORE = 9
KEYEVENTF_KEYUP = 0x0002
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
VK = {'a': 0x41, 'd': 0x44, 's': 0x53, 'w': 0x57, 'z': 0x5A,
      'x': 0x58, 'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27}
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]


class INPUT_UNION(ctypes.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', wintypes.DWORD), ('data', INPUT_UNION)]


class RECT(ctypes.Structure):
    _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG),
                ('right', wintypes.LONG), ('bottom', wintypes.LONG)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG),
                ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG),
                ('biYPelsPerMeter', wintypes.LONG), ('biClrUsed', wintypes.DWORD),
                ('biClrImportant', wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', wintypes.DWORD * 3)]


user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
                               wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                         wintypes.DWORD]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                            wintypes.UINT, ctypes.c_void_p,
                            ctypes.POINTER(BITMAPINFO), wintypes.UINT]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def active_cemu_pids():
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Cemu.exe', '/FO', 'CSV', '/NH'],
                            check=True, capture_output=True, text=True, encoding='mbcs')
    rows = list(csv.reader(line for line in result.stdout.splitlines()
                           if line.strip() and not line.startswith('INFO:')))
    return [int(row[1]) for row in rows if len(row) >= 2 and row[0].casefold() == 'cemu.exe']


def process_for_window(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def process_image_path(pid):
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return Path(buffer.value).resolve()
    finally:
        kernel32.CloseHandle(handle)


def windows_for_pid(pid):
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):
        if process_for_window(hwnd) != pid or not user32.IsWindowVisible(hwnd):
            return True
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width < 320 or height < 240:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        found.append({'hwnd': hwnd, 'title': title.value, 'rect': rect,
                      'width': width, 'height': height})
        return True

    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    return found


def main_game_windows(windows):
    """Prefer Cemu's actual title window when auxiliary views are also open."""
    titled = [window for window in windows if window['title']]
    game_windows = [window for window in titled
                    if 'TitleId:' in window['title'] or
                    'New SUPER MARIO BROS.' in window['title']]
    return game_windows or titled


def choose_window(pid):
    windows = windows_for_pid(pid)
    if not windows:
        raise RuntimeError(f'Cemu PID {pid} has no visible game window.')
    candidates = main_game_windows(windows)
    if len(candidates) != 1:
        details = [{'hwnd': int(window['hwnd']), 'title': window['title'],
                    'rect': [window['rect'].left, window['rect'].top,
                             window['rect'].right, window['rect'].bottom]}
                   for window in candidates]
        raise RuntimeError(f'Cemu PID {pid} has ambiguous top-level windows: {details}')
    return candidates[0]


def focus_and_verify(pid, hwnd, timeout=30.):
    active = active_cemu_pids()
    if pid not in active:
        raise RuntimeError(f'Test Cemu PID {pid} is no longer active; active Cemu PIDs are {active}.')
    if process_for_window(hwnd) != pid or not user32.IsWindow(hwnd):
        raise RuntimeError('Selected Cemu HWND no longer belongs to the launched PID.')
    candidates = main_game_windows(windows_for_pid(pid))
    if len(candidates) != 1 or int(candidates[0]['hwnd']) != int(hwnd):
        raise RuntimeError('The launched Cemu PID no longer has exactly the selected titled window.')
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.AllowSetForegroundWindow(pid)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        foreground = user32.GetForegroundWindow()
        if foreground == hwnd and process_for_window(foreground) == pid:
            return int(foreground)
        time.sleep(0.05)
    foreground = user32.GetForegroundWindow()
    foreground_pid = process_for_window(foreground) if foreground else None
    raise RuntimeError(
        f'Focus verification failed: foreground HWND {int(foreground) if foreground else None} '
        f'(PID {foreground_pid}), expected HWND {int(hwnd)} (PID {pid}) after {timeout:g}s. '
        'Activate the exact returned Cemu window through Computer Use before retrying.')


def send_inputs(inputs):
    array = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(array), array, ctypes.sizeof(INPUT))
    if sent != len(array):
        raise ctypes.WinError(ctypes.get_last_error())


def key_event(key, down):
    scan = user32.MapVirtualKeyW(VK[key], 0)
    event = INPUT(type=INPUT_KEYBOARD,
                  ki=KEYBDINPUT(VK[key], scan, 0 if down else KEYEVENTF_KEYUP,
                                0, 0))
    send_inputs([event])


def click_window_center(window):
    x = window['rect'].left + window['width'] // 2
    y = window['rect'].top + window['height'] // 2
    if not user32.SetCursorPos(x, y):
        raise ctypes.WinError(ctypes.get_last_error())
    down = INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0))
    up = INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0))
    send_inputs([down, up])


def advance_title(window, *, click=False, hold_ms=500):
    """Advance the game title using its observed mouse prompt or mapped A key."""
    if click:
        click_window_center(window)
        return "mouse_click"
    key_event('z', True)
    time.sleep(hold_ms / 1000.)
    key_event('z', False)
    return "gamepad_a"


def wait_for_confirmation(prompt, *, pid, process=None):
    """Return True on Enter, False on N/Esc, or fail if the tested Cemu exits."""
    if not sys.stdin.isatty():
        answer = input(prompt).strip().casefold()
        return answer not in {'n', 'no', 'q', 'quit'}
    sys.stdout.write(prompt)
    sys.stdout.flush()
    while True:
        if process is not None:
            exit_code = process.poll()
            if exit_code is not None:
                raise RuntimeError(
                    f'Cemu PID {pid} exited with code {exit_code} while waiting for confirmation.')
        elif pid not in active_cemu_pids():
            raise RuntimeError(
                f'Attached Cemu PID {pid} exited while waiting for confirmation.')
        if msvcrt.kbhit():
            key = msvcrt.getwch()
            if key == '\x03':
                raise KeyboardInterrupt
            if key in ('\r', '\n'):
                sys.stdout.write('\n')
                sys.stdout.flush()
                return True
            if key.casefold() in ('n', 'q') or key == '\x1b':
                sys.stdout.write('\nAborted at confirmation gate.\n')
                sys.stdout.flush()
                return False
        time.sleep(0.05)


def confirm_or_abort(report, prompt, gate, *, pid, process=None):
    """Record a manual gate and let the operator stop without sending more input."""
    confirmed = wait_for_confirmation(prompt, pid=pid, process=process)
    report['events'].append({'time': timestamp(),
                             'action': 'manual_gate_confirmed' if confirmed else 'manual_gate_aborted',
                             'gate': gate})
    if not confirmed:
        report['status'] = 'aborted'
        report['abort_gate'] = gate
    return confirmed


def map_confirmation_prompt(start_label=None):
    if start_label:
        return (f'Inspect the saved map screenshot. Press Enter only if Mario is standing at '
                f'{start_label!r}; press N or Esc to abort: ')
    return ('Inspect the saved map screenshot. Press Enter only if the intended start node is visible; '
            'press N or Esc to abort: ')


def step_review_prompt(case, index, key, next_key=None):
    next_step = f' Next direction is {next_key.upper()}.' if next_key else ' This was the final direction.'
    return (f'Inspect {case}-step-{index}-{key}-after.bmp. Confirm Mario reached the expected '
            f'next node before continuing.{next_step} Press Enter to continue or N/Esc to stop: ')


def capture_window(hwnd, path: Path):
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    width, height = rect.right - rect.left, rect.bottom - rect.top
    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not gdi32.BitBlt(memory_dc, 0, 0, width, height, window_dc, 0, 0, SRCCOPY):
            raise ctypes.WinError(ctypes.get_last_error())
        gdi32.SelectObject(memory_dc, previous)
        info = BITMAPINFO()
        info.bmiHeader = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height,
                                          1, 32, 0, width * height * 4, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width * height * 4)
        lines = gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels,
                                ctypes.byref(info), DIB_RGB_COLORS)
        if lines != height:
            raise ctypes.WinError(ctypes.get_last_error())
        pixel_data = pixels.raw
        file_header = struct.pack('<2sIHHI', b'BM', 14 + 40 + len(pixel_data), 0, 0, 54)
        path.write_bytes(file_header + bytes(info.bmiHeader) + pixel_data)
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def save_hashes(profile):
    root = profile / 'mlc01/usr/save/00050000/10101D00/user'
    result = {}
    if root.is_dir():
        for path in sorted(root.rglob('*')):
            if path.is_file() and not path.is_symlink():
                result[path.relative_to(root).as_posix()] = {
                    'size': path.stat().st_size, 'sha256': sha256(path)}
    return result


def record_final_artifacts(report, profile):
    """Attach save and log evidence even when focus or a manual gate fails."""
    profile = Path(profile)
    report['final_save_hashes'] = save_hashes(profile)
    log_path = profile / 'log.txt'
    report['game_log'] = str(log_path.resolve())
    report['game_log_sha256'] = sha256(log_path) if log_path.is_file() else None


def record_prelaunch_failure(report, args, profile, message):
    report['prelaunch_error'] = message
    report['finished_at'] = timestamp()
    record_final_artifacts(report, profile)
    args.screenshot_dir.mkdir(parents=True, exist_ok=True)
    result_path = args.screenshot_dir / f'{args.case}-result.json'
    result_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Result: {result_path.resolve()}')


def compare_controller_profiles(controller_path, reference_profile):
    """Require byte-identical controller mappings for a matched Cemu run."""
    reference_profile = Path(reference_profile).resolve(strict=True)
    if not reference_profile.is_dir():
        raise ValueError('Controller comparison reference must be a Cemu profile directory')
    reference_controller = reference_profile / 'controllerProfiles/controller0.txt'
    if not reference_controller.is_file():
        reference_controller = reference_profile / 'controllerProfiles/controller0.xml'
    current_hash = sha256(controller_path) if Path(controller_path).is_file() else None
    reference_hash = (sha256(reference_controller)
                      if reference_controller.is_file() else None)
    return {
        'reference_profile': str(reference_profile),
        'controller_profile': str(controller_path),
        'controller_sha256': current_hash,
        'reference_controller_profile': str(reference_controller),
        'reference_controller_sha256': reference_hash,
        'matches': bool(current_hash and reference_hash and current_hash == reference_hash),
    }


def run(args):
    profile = args.profile.resolve(strict=True)
    rpx = args.rpx.resolve(strict=True)
    exe = profile / 'Cemu.exe'
    if not exe.is_file():
        raise ValueError(f'Cemu.exe not found in profile {profile}')
    current = active_cemu_pids()
    if args.key not in ('w', 'a', 's', 'd') or (args.keys and any(k not in VK or k == 'z' for k in args.keys)):
        raise ValueError('Movement key must be W, A, S, or D')
    args.screenshot_dir.mkdir(parents=True, exist_ok=True)
    controller = profile / 'controllerProfiles/controller0.txt'
    if not controller.is_file():
        controller = profile / 'controllerProfiles/controller0.xml'
    pack = args.pack_file.resolve(strict=True) if args.pack_file else None
    profile_pack = (profile / 'graphicPacks' / args.pack_name / 'content/Common/course_select/CS_W1.szs')
    report = {
        'case': args.case,
        'started_at': timestamp(),
        'profile': str(profile),
        'cemu_executable': str(exe.resolve()),
        'cemu_executable_sha256': sha256(exe),
        'rpx': str(rpx),
        'rpx_sha256': sha256(rpx),
        'cemu_pids_before_launch': current,
        'pack_file': str(pack) if pack else None,
        'pack_name': args.pack_name,
        'pack_sha256': sha256(pack) if pack else None,
        'profile_pack_sha256': sha256(profile_pack) if profile_pack.is_file() else None,
        'controller_profile': str(controller),
        'controller_sha256': sha256(controller) if controller.is_file() else None,
        'key': args.key,
        'keys': args.keys,
        'sequence': args.sequence,
        'start_label': args.start_label,
        'pause_after_each_step': args.pause_after_each_step,
        'hold_ms': args.hold_ms,
        'navigation_key': args.navigation_key,
        'navigation_hold_ms': args.navigation_hold_ms,
        'baseline_save_hashes': save_hashes(profile),
        'events': [],
    }
    if args.compare_controller_to is not None:
        try:
            report['controller_comparison'] = compare_controller_profiles(
                controller, args.compare_controller_to)
        except (OSError, ValueError) as error:
            record_prelaunch_failure(report, args, profile, str(error))
            raise ValueError(f'Controller-profile comparison failed: {error}') from error
        if not report['controller_comparison']['matches']:
            message = ('Controller profile does not byte-match reference profile: '
                       f"{report['controller_comparison']['reference_profile']}")
            record_prelaunch_failure(report, args, profile, message)
            raise ValueError(message)
    if args.pack_file:
        report['pack_matches_profile_copy'] = (
            sha256(pack) == sha256(profile_pack) if profile_pack.is_file() else None)
        if not report['pack_matches_profile_copy']:
            message = (f"The requested pack archive does not match {profile_pack}; "
                       "refusing to launch the wrong build.")
            record_prelaunch_failure(report, args, profile, message)
            raise ValueError(message)
    if args.graph_profile is not None:
        try:
            from tools.cemu_preflight import inspect_profile
            report['profile_preflight'] = inspect_profile(
                profile, expected_pack=args.pack_name, archive=pack,
                require_keyboard=True, require_gamepad_a=args.enter_level,
                compare_save_to=args.compare_save_to,
                graph_profile=args.graph_profile)
        except (OSError, ValueError) as error:
            report['profile_preflight_error'] = str(error)
            record_prelaunch_failure(report, args, profile, str(error))
            raise ValueError(f'Graph-profile preflight failed: {error}') from error
        if not report['profile_preflight']['ready']:
            issues = report['profile_preflight']['issues']
            message = 'Cemu preflight blocked launch: ' + '; '.join(issues)
            record_prelaunch_failure(report, args, profile, message)
            raise RuntimeError(message)
    if args.attach:
        if len(current) != 1:
            raise RuntimeError(f'Attach mode requires exactly one active Cemu process; found {current}.')
        pid = current[0]
        if process_image_path(pid).resolve() != exe.resolve():
            raise RuntimeError(
                f'Active Cemu PID {pid} is {process_image_path(pid)}, expected {exe.resolve()}.')
        process = None
    else:
        if current:
            raise RuntimeError(f'Refusing to start a second Cemu instance; already active PIDs: {current}.')
        process = subprocess.Popen([str(exe), '-g', str(rpx), '-m', str(profile / 'mlc01')],
                                   cwd=profile)
        pid = process.pid
        if pid in current:
            raise RuntimeError('Launched Cemu PID unexpectedly matches a pre-existing process.')
    report['pid'] = pid
    window = None
    pressed = set()
    try:
        deadline = time.monotonic() + args.window_timeout
        while time.monotonic() < deadline and (args.attach or process.poll() is None):
            windows = windows_for_pid(pid)
            candidates = main_game_windows(windows)
            if candidates:
                if len(candidates) != 1:
                    details = [{'hwnd': int(candidate['hwnd']),
                                'title': candidate['title']} for candidate in candidates]
                    raise RuntimeError(
                        f'Expected one main game window for Cemu PID {pid}; found {details}')
                window = candidates[0]
                break
            time.sleep(0.1)
        if window is None:
            raise RuntimeError('Cemu did not create one identifiable main game window before timeout.')
        report['hwnd'] = int(window['hwnd'])
        report['window_title'] = window['title']
        report['window_rect'] = [window['rect'].left, window['rect'].top,
                                 window['rect'].right, window['rect'].bottom]
        report['screenshots'] = {}

        title_capture = args.screenshot_dir / f'{args.case}-launch.bmp'
        capture_window(window['hwnd'], title_capture)
        report['screenshots']['launch'] = str(title_capture.resolve())
        report['events'].append({'time': timestamp(), 'action': 'window_capture_before_focus',
                                 'hwnd': int(window['hwnd']), 'pid': pid})
        foreground = focus_and_verify(pid, window['hwnd'], args.focus_timeout)
        report['events'].append({'time': timestamp(), 'action': 'focus_verified',
                                 'foreground_hwnd': foreground, 'pid': pid})
        if args.navigation_only:
            foreground = focus_and_verify(pid, window['hwnd'], args.focus_timeout)
            before = args.screenshot_dir / f'{args.case}-before-{args.navigation_key}.bmp'
            capture_window(window['hwnd'], before)
            report['screenshots']['navigation_before'] = str(before.resolve())
            key_event(args.navigation_key, True)
            pressed.add(args.navigation_key)
            report['events'].append({'time': timestamp(), 'action': 'navigation_key_down',
                                     'key': args.navigation_key,
                                     'hold_ms': args.navigation_hold_ms,
                                     'foreground_hwnd': foreground})
            time.sleep(args.navigation_hold_ms / 1000.)
            key_event(args.navigation_key, False)
            pressed.discard(args.navigation_key)
            report['events'].append({'time': timestamp(), 'action': 'navigation_key_up',
                                     'key': args.navigation_key})
            time.sleep(args.settle_wait)
            after = args.screenshot_dir / f'{args.case}-after-{args.navigation_key}.bmp'
            capture_window(window['hwnd'], after)
            report['screenshots']['navigation_after'] = str(after.resolve())
            report['events'].append({'time': timestamp(), 'action': 'navigation_capture_complete'})
            report['final_save_hashes'] = save_hashes(profile)
            report['game_log'] = str((profile / 'log.txt').resolve())
            report['game_log_sha256'] = sha256(profile / 'log.txt') if (profile / 'log.txt').is_file() else None
            return
        if args.press_title_a or getattr(args, 'click_title', False):
            click_title = getattr(args, 'click_title', False)
            auto_title = (getattr(args, 'auto_click_title', False) if click_title
                          else args.auto_press_title_a)
            if auto_title:
                time.sleep(args.title_a_delay_ms / 1000.)
                report['events'].append({'time': timestamp(),
                                         'action': 'title_click_ready_delay' if click_title
                                         else 'title_a_ready_delay',
                                         'delay_ms': args.title_a_delay_ms})
            else:
                if not confirm_or_abort(
                        report,
                        ('Inspect the exact Cemu window. When "Press 2!" is visible, press Enter here; N/Esc aborts: '
                         if click_title else
                         'Inspect the exact Cemu window. When "Press A!" is visible, press Enter here; N/Esc aborts: '),
                        'title_screen', pid=pid, process=process):
                    return
            foreground = focus_and_verify(pid, window['hwnd'], args.focus_timeout)
            action = advance_title(window, click=click_title,
                                   hold_ms=args.title_key_hold_ms)
            if click_title:
                report['events'].append({'time': timestamp(), 'action': 'title_mouse_click',
                                         'button': 'left', 'target': 'window_center',
                                         'foreground_hwnd': foreground})
            else:
                report['events'].append({'time': timestamp(), 'action': 'title_a_key',
                                         'key': 'z', 'button': 'A',
                                         'hold_ms': args.title_key_hold_ms,
                                         'foreground_hwnd': foreground})
            time.sleep(args.transition_wait)
            title_advance = args.screenshot_dir / (
                f'{args.case}-after-title-click.bmp' if action == 'mouse_click'
                else f'{args.case}-after-title-a.bmp')
            capture_window(window['hwnd'], title_advance)
            report['screenshots']['after_title_click' if action == 'mouse_click'
                                  else 'after_title_a'] = str(title_advance.resolve())
        if args.attach:
            if not confirm_or_abort(
                    report,
                    'Verify the attached Cemu window shows the intended overworld; Enter continues, N/Esc aborts: ',
                    'overworld_visible', pid=pid, process=process):
                return
        else:
            if not confirm_or_abort(
                    report,
                    'Pass the title/start screens. When the intended overworld is visible, press Enter; N/Esc aborts: ',
                    'overworld_visible', pid=pid, process=process):
                return
        foreground = focus_and_verify(pid, window['hwnd'], args.focus_timeout)
        report['events'].append({'time': timestamp(), 'action': 'overworld_focus_verified',
                                 'foreground_hwnd': foreground, 'pid': pid})
        map_capture = args.screenshot_dir / f'{args.case}-map-check.bmp'
        capture_window(window['hwnd'], map_capture)
        report['screenshots']['map_check'] = str(map_capture.resolve())
        if not confirm_or_abort(report, map_confirmation_prompt(args.start_label),
                                'starting_node', pid=pid, process=process):
            return

        before = args.screenshot_dir / f'{args.case}-before-{"".join(args.keys or args.key)}.bmp'
        foreground = focus_and_verify(pid, window['hwnd'], args.focus_timeout)
        capture_window(window['hwnd'], before)
        report['screenshots']['before'] = str(before.resolve())
        report['events'].append({'time': timestamp(), 'action': 'movement_start_capture',
                                 'foreground_hwnd': foreground})

        foreground = focus_and_verify(pid, window['hwnd'], args.focus_timeout)
        keys = list(args.sequence or args.keys or args.key)
        if args.sequence:
            for index, key in enumerate(keys, 1):
                foreground = focus_and_verify(pid, window['hwnd'], args.focus_timeout)
                step_before = args.screenshot_dir / f'{args.case}-step-{index}-{key}-before.bmp'
                capture_window(window['hwnd'], step_before)
                report['screenshots'][f'step_{index}_before'] = str(step_before.resolve())
                key_event(key, True)
                pressed.add(key)
                report['events'].append({'time': timestamp(), 'action': 'sequence_key_down',
                                         'step': index, 'key': key,
                                         'hold_ms': args.hold_ms,
                                         'foreground_hwnd': foreground})
                time.sleep(args.hold_ms / 1000.)
                key_event(key, False)
                pressed.discard(key)
                report['events'].append({'time': timestamp(), 'action': 'sequence_key_up',
                                         'step': index, 'key': key})
                time.sleep(args.settle_wait)
                step_after = args.screenshot_dir / f'{args.case}-step-{index}-{key}-after.bmp'
                capture_window(window['hwnd'], step_after)
                report['screenshots'][f'step_{index}_after'] = str(step_after.resolve())
                if args.pause_after_each_step and index < len(keys):
                    next_key = keys[index] if index < len(keys) else None
                    if not confirm_or_abort(
                            report, step_review_prompt(args.case, index, key, next_key),
                            f'step_{index}_{key}', pid=pid, process=process):
                        return
                    report['events'].append({'time': timestamp(),
                                             'action': 'step_review_confirmed',
                                             'step': index, 'key': key,
                                             'next_key': next_key,
                                             'screenshot': str(step_after.resolve())})
        else:
            for key in keys:
                key_event(key, True)
                pressed.add(key)
            report['events'].append({'time': timestamp(), 'action': 'key_down', 'keys': keys,
                                     'hold_ms': args.hold_ms, 'foreground_hwnd': foreground})
            time.sleep(args.hold_ms / 1000.)
            for key in reversed(keys):
                key_event(key, False)
                pressed.discard(key)
            report['events'].append({'time': timestamp(), 'action': 'key_up', 'keys': keys})
            time.sleep(args.settle_wait)
            after = args.screenshot_dir / f'{args.case}-after-{"".join(keys)}.bmp'
            capture_window(window['hwnd'], after)
            report['screenshots']['after'] = str(after.resolve())
        if args.enter_level:
            if not confirm_or_abort(
                    report,
                    'Verify Mario is on the intended course node. Enter sends Z/A once; N/Esc aborts: ',
                    'level_entry', pid=pid, process=process):
                return
            foreground = focus_and_verify(pid, window['hwnd'], args.focus_timeout)
            key_event('z', True)
            time.sleep(args.level_key_hold_ms / 1000.)
            key_event('z', False)
            report['events'].append({'time': timestamp(), 'action': 'level_enter_key',
                                     'key': 'z', 'hold_ms': args.level_key_hold_ms,
                                     'foreground_hwnd': foreground})
            time.sleep(args.level_wait)
            level_capture = args.screenshot_dir / f'{args.case}-level-result.bmp'
            capture_window(window['hwnd'], level_capture)
            report['screenshots']['level_result'] = str(level_capture.resolve())
        report['final_save_hashes'] = save_hashes(profile)
        report['game_log'] = str((profile / 'log.txt').resolve())
        report['game_log_sha256'] = sha256(profile / 'log.txt') if (profile / 'log.txt').is_file() else None
        report.setdefault('status', 'completed')
    except (OSError, ValueError, RuntimeError) as error:
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        for key in list(pressed):
            key_event(key, False)
        if not args.attach and process.poll() is None and window and user32.IsWindow(window['hwnd']):
            user32.PostMessageW(window['hwnd'], WM_CLOSE, 0, 0)
        if args.attach:
            report['exit_code'] = None
            report['attached_process_left_running'] = True
        else:
            try:
                process.wait(timeout=args.close_timeout)
            except subprocess.TimeoutExpired:
                report['close_error'] = f'Cemu PID {process.pid} did not close after WM_CLOSE; left running, not force-killed.'
            report['exit_code'] = process.poll()
        record_final_artifacts(report, profile)
        report['finished_at'] = timestamp()
        args.screenshot_dir.mkdir(parents=True, exist_ok=True)
        result_path = args.screenshot_dir / f'{args.case}-result.json'
        result_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'Result: {result_path.resolve()}')
        print(f'Screenshots: {args.screenshot_dir.resolve()}')
        if 'close_error' in report:
            print(report['close_error'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--rpx', required=True, type=Path)
    parser.add_argument('--case', required=True, help='Short result/screenshot filename prefix')
    parser.add_argument('--screenshot-dir', type=Path, default=Path('local/evidence/cemu-input-test'))
    parser.add_argument('--key', choices=('w', 'a', 's', 'd'), default='d')
    parser.add_argument('--keys', choices=('w', 'a', 's', 'd'), nargs='+',
                        help='Held key chord, for example --keys a w')
    parser.add_argument('--sequence', choices=('w', 'a', 's', 'd'), nargs='+',
                        help='Apply directions one at a time, capturing the map before and after each key')
    parser.add_argument('--start-label',
                        help='Expected visible starting node name; included in the explicit map confirmation prompt and result')
    parser.add_argument('--pause-after-each-step', action='store_true',
                        help='With --sequence, pause after each screenshot for node-by-node visual confirmation before the next direction')
    parser.add_argument('--attach', action='store_true',
                        help='Attach to the one active Cemu whose executable is in --profile; do not close it')
    parser.add_argument('--navigation-only', action='store_true',
                        help='Send one held menu-navigation key to the attached Cemu and capture before/after screenshots')
    parser.add_argument('--navigation-key', choices=('up', 'down', 'left', 'right', 'x', 'z'),
                        help='Key for --navigation-only; arrow keys use the configured keyboard D-pad mapping')
    parser.add_argument('--navigation-hold-ms', type=int, default=700,
                        help='Navigation-key hold duration, 100-5000 ms (default 700)')
    parser.add_argument('--press-title-a', action='store_true',
                        help='Send the configured Z=A key once to the verified game window before the manual start flow')
    parser.add_argument('--auto-press-title-a', action='store_true',
                        help='Send Z=A after the title delay instead of waiting for a manual title-screen confirmation')
    parser.add_argument('--click-title', action='store_true',
                        help='After confirming the visible "Press 2!" prompt, left-click the exact Cemu game-window center')
    parser.add_argument('--auto-click-title', action='store_true',
                        help='Left-click the exact game-window center after the title delay instead of waiting for confirmation')
    parser.add_argument('--title-a-delay-ms', type=int, default=5500,
                        help='Wait after Cemu creates its window before auto title A (100-20000 ms; default 5500)')
    parser.add_argument('--title-key-hold-ms', type=int, default=500)
    parser.add_argument('--hold-ms', type=int, default=1500)
    parser.add_argument('--focus-timeout', type=float, default=30.)
    parser.add_argument('--pack-file', type=Path,
                        help='Exact W1 archive to hash and compare to this profile copy')
    parser.add_argument('--graph-profile', type=Path,
                        help='Require this passing static graph profile in the packed export manifest before launching')
    parser.add_argument('--compare-save-to', type=Path, metavar='PROFILE',
                        help='Require identical NSMBU saves before launch')
    parser.add_argument('--compare-controller-to', type=Path, metavar='PROFILE',
                        help='Require a byte-identical controller profile to another Cemu profile')
    parser.add_argument('--pack-name', default='WorldStudioChain',
                        help='Graphic-pack folder name inside the isolated profile')
    parser.add_argument('--enter-level', action='store_true',
                        help='After movement, wait for confirmation on the destination node and press Z/A')
    parser.add_argument('--level-key-hold-ms', type=int, default=700)
    parser.add_argument('--level-wait', type=float, default=15.)
    parser.add_argument('--window-timeout', type=float, default=30.)
    parser.add_argument('--transition-wait', type=float, default=5.)
    parser.add_argument('--settle-wait', type=float, default=2.)
    parser.add_argument('--close-timeout', type=float, default=20.)
    args = parser.parse_args(argv)
    if not args.case or any(character not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for character in args.case):
        parser.error('--case may contain only ASCII letters, digits, dash and underscore')
    if not 100 <= args.hold_ms <= 10000:
        parser.error('--hold-ms must be between 100 and 10000')
    if not 100 <= args.title_key_hold_ms <= 3000:
        parser.error('--title-key-hold-ms must be between 100 and 3000')
    if not 100 <= args.title_a_delay_ms <= 20000:
        parser.error('--title-a-delay-ms must be between 100 and 20000')
    if args.auto_press_title_a and not args.press_title_a:
        parser.error('--auto-press-title-a requires --press-title-a')
    if args.click_title and args.press_title_a:
        parser.error('--click-title and --press-title-a are mutually exclusive')
    if args.auto_click_title and not args.click_title:
        parser.error('--auto-click-title requires --click-title')
    if args.navigation_only and (not args.attach or not args.navigation_key):
        parser.error('--navigation-only requires --attach and --navigation-key')
    if not 100 <= args.navigation_hold_ms <= 5000:
        parser.error('--navigation-hold-ms must be between 100 and 5000')
    if args.keys and len(set(args.keys)) != len(args.keys):
        parser.error('--keys cannot contain a duplicate key')
    if args.sequence and args.keys:
        parser.error('--sequence and --keys are mutually exclusive')
    if args.pause_after_each_step and not args.sequence:
        parser.error('--pause-after-each-step requires --sequence')
    if args.start_label is not None and not args.start_label.strip():
        parser.error('--start-label cannot be empty')
    if not args.pack_name or any(character not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for character in args.pack_name):
        parser.error('--pack-name may contain only ASCII letters, digits, dash and underscore')
    if args.graph_profile and not args.pack_file:
        parser.error('--graph-profile requires --pack-file')
    try:
        run(args)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f'Cemu test not run: {error}\n')


if __name__ == '__main__':
    main()
