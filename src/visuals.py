"""Local, window-only snapshots and bookmarks on the recording's pause-aware clock."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import io
import json
from pathlib import Path
import threading
import time

from PIL import Image


@dataclass(frozen=True)
class WindowTarget:
    hwnd: int
    pid: int
    title: str


def teams_windows():
    """Enumerate visible Teams top-level windows; selection belongs to the user."""
    user = ctypes.windll.user32
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                               wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    targets = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        title = ctypes.create_unicode_buffer(1024)
        user.GetWindowTextW(hwnd, title, len(title))
        if not title.value or not user.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                path, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
                if kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
                    if Path(path.value).name.lower() in ('ms-teams.exe', 'teams.exe'):
                        targets.append(WindowTarget(hwnd, pid.value, title.value))
            finally:
                kernel.CloseHandle(handle)
        return True

    user.EnumWindows(visit, 0)
    return targets


def window_status(target):
    user = ctypes.windll.user32
    hwnd = wintypes.HWND(target.hwnd)
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not user.IsWindow(hwnd) or pid.value != target.pid:
        return '窗口已关闭'
    if user.IsIconic(hwnd) or not user.IsWindowVisible(hwnd):
        return '窗口已最小化或隐藏'
    return ''


class VisualTimeline:
    def __init__(self, folder, clock):
        self.folder, self.clock = Path(folder), clock
        self.lock = threading.Lock()
        self.closed = False
        self.frames = self.markers = 0
        self._last_jpeg = None
        self._events = (self.folder / 'timeline.jsonl').open('x', encoding='utf-8')

    def _append(self, kind, **fields):
        event = {'type': kind, 'seconds': round(self.clock(), 3), **fields}
        self._events.write(json.dumps(event, ensure_ascii=False) + '\n')
        self._events.flush()
        return event

    def note(self, text):
        with self.lock:
            if not self.closed:
                self._append('status', text=text)

    def mark(self):
        with self.lock:
            if self.closed:
                return None
            self.markers += 1
            return self._append('marker', label=f'标记 {self.markers}')

    def snapshot(self, image, seconds):
        image = image.convert('RGB')
        image.thumbnail((1280, 720), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, 'JPEG', quality=65, optimize=True)
        data = output.getvalue()
        with self.lock:
            if self.closed or data == self._last_jpeg:
                return
            path = f'screenshots/{self.frames + 1:06d}.jpg'
            (self.folder / 'screenshots').mkdir(exist_ok=True)
            (self.folder / path).write_bytes(data)
            self._append('frame', seconds=round(seconds, 3), file=path,
                         width=image.width, height=image.height)
            self._last_jpeg = data
            self.frames += 1

    def finish(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self._events.close()
        write_review(self.folder)


class WindowSnapshots:
    STOP_TIMEOUT = 3

    def __init__(self, target, timeline, active, report):
        self.target, self.timeline = target, timeline
        self.active, self.report = active, report
        self.control = None
        self._last_capture = -float('inf')
        self._stopped = False
        self.status = '等待窗口画面'
        self.failure = ''
        self._last_reason = ''

    def poll_status(self):
        reason = window_status(self.target)
        if reason != self._last_reason:
            self._last_reason = reason
            self.timeline.note(reason + '；截图暂停，录音继续' if reason else '窗口已恢复')
        if self.failure:
            return self.failure
        return reason + '；截图暂停，录音继续' if reason else self.status

    def start(self):
        reason = window_status(self.target)
        if reason:
            raise ValueError(reason + '，请恢复并重新选择 Teams 会议窗口。')
        from windows_capture import WindowsCapture
        self.capture = WindowsCapture(window_hwnd=self.target.hwnd, cursor_capture=False, draw_border=False,
                                      secondary_window=False, minimum_update_interval=3000)
        self.capture.frame_handler = self._frame
        self.capture.closed_handler = self._closed
        self.timeline.note('绑定窗口：' + self.target.title)
        self.control = self.capture.start_free_threaded()

    def _frame(self, frame, control):
        try:
            if self._stopped or not self.active():
                return
            reason = window_status(self.target)
            if reason:
                self.status = reason + '；截图暂停，录音继续'
                return
            now = time.monotonic()
            if now - self._last_capture < 2.95:
                return
            seconds = self.timeline.clock()
            # Copy only the bound window's BGRA frame; no desktop fallback.
            image = Image.fromarray(frame.frame_buffer[:, :, :3][:, :, ::-1].copy())
            if self.active() and not self._stopped:
                self.timeline.snapshot(image, seconds)
                self._last_capture = now
                self.status = f'截图中 · 已保存 {self.timeline.frames} 张'
        except Exception as exc:
            self.failure = f'截图停止，录音继续：{exc}'
            self.status = self.failure
            self.timeline.note(self.failure)
            self.report(self.failure)
            control.stop()

    def _closed(self):
        if not self._stopped:
            self.failure = '会议窗口已关闭；截图停止，录音继续'
            self.status = self.failure
            self.timeline.note(self.failure)
            self.report(self.failure)

    def stop(self):
        self._stopped = True
        if self.control:
            control, self.control = self.control, None
            done, errors = threading.Event(), []
            def stop_native():
                try:
                    control.stop()
                except Exception as exc:
                    errors.append(exc)
                finally:
                    done.set()
            # A native capture shutdown must never hold the audio files open.
            threading.Thread(target=stop_native, daemon=True).start()
            if not done.wait(self.STOP_TIMEOUT):
                raise RuntimeError('截图组件退出超时；不再写入截图，音频已停止保存')
            if errors:
                raise errors[0]


def write_review(folder):
    events = [json.loads(line) for line in (folder / 'timeline.jsonl').read_text(encoding='utf-8').splitlines()]
    # Inline JSON cannot close the script element, even for user-controlled window titles.
    data = json.dumps(events, ensure_ascii=False).replace('<', '\\u003c')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>WaveGrab · 会议回看</title><style>
body{font:16px system-ui;margin:24px auto;padding:0 20px;max-width:1280px;background:#f4f7f9;color:#243141}
audio{width:100%}button{padding:9px 14px;margin:4px;border:1px solid #c9d7df;border-radius:8px;background:white;cursor:pointer}
img{display:block;max-width:100%;max-height:70vh;margin:12px auto;border-radius:8px}
input{width:100%}#notice{color:#675323}small{color:#5b6975}
</style><h1>会议回看</h1><p>点击标记跳转；音频不会自动播放。拖动画面时间轴也可定位。</p>
<audio id="audio" controls preload="metadata" src="mixed.flac"></audio>
<div id="marks"></div><input id="seek" aria-label="画面时间轴" type="range" min="0" value="0" step="0.1">
<p id="position"></p><p id="notice"></p><img id="shot" alt="选定会议窗口的截图" hidden><small id="notes"></small>
<script>const events=__DATA__;
const audio=document.getElementById('audio'),seek=document.getElementById('seek'),shot=document.getElementById('shot');
const frames=events.filter(e=>e.type==='frame'), markers=events.filter(e=>e.type==='marker');
function stamp(t){return new Date(Math.max(0,t)*1000).toISOString().slice(11,19)}
function show(t){seek.value=t;document.getElementById('position').textContent=stamp(t);
 const f=frames.filter(e=>e.seconds<=t).at(-1);shot.hidden=!f;
 if(f){if(shot.getAttribute('src')!==f.file)shot.src=f.file;shot.alt='会议画面 '+stamp(f.seconds)}
 document.getElementById('notice').textContent=f?'画面采集于 '+stamp(f.seconds)+'；暂停截图或静止时沿用上一张。':'此时间点没有截图。';}
function jump(t){show(t);if(audio.readyState>0)audio.currentTime=t}
for(const m of markers){const b=document.createElement('button');b.textContent=stamp(m.seconds)+' · '+m.label;b.onclick=()=>jump(m.seconds);document.getElementById('marks').append(b)}
if(!markers.length)document.getElementById('marks').textContent='本次没有标记';
seek.max=Math.max(1,...events.map(e=>e.seconds));seek.oninput=()=>jump(Number(seek.value));
audio.onloadedmetadata=()=>{if(Number.isFinite(audio.duration))seek.max=audio.duration};audio.ontimeupdate=()=>show(audio.currentTime);
document.getElementById('notes').textContent=events.filter(e=>e.type==='status').map(e=>stamp(e.seconds)+' '+e.text).join(' / ');show(0);
</script></html>'''
    (folder / 'review.html').write_text(page.replace('__DATA__', data), encoding='utf-8')
