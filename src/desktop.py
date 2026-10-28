"""Tray controls and Windows global hotkeys; all actions are posted to Tk."""
import ctypes
from ctypes import wintypes
import threading

from PIL import Image, ImageDraw
import pystray


class DesktopControls:
    def __init__(self, post, show, toggle, mark, review, quit_app, report):
        self.post, self.report = post, report
        self.toggle, self.mark = toggle, mark
        self.state = '就绪'
        self.ready = threading.Event()
        self.hotkey_ready = threading.Event()
        self.hotkey_thread_id = None
        self.thread = None
        self.icon = pystray.Icon('WaveGrab', self._image('就绪'), 'WaveGrab · 就绪', pystray.Menu(
            pystray.MenuItem('打开 WaveGrab', lambda *_: post(show), default=True),
            pystray.MenuItem('开始 / 停止录音  Alt+R', lambda *_: post(toggle)),
            pystray.MenuItem('打标  Alt+M', lambda *_: post(mark)),
            pystray.MenuItem('回看最近录音', lambda *_: post(review)),
            pystray.MenuItem('退出', lambda *_: post(quit_app))))

    @staticmethod
    def _image(state):
        image = Image.new('RGBA', (64, 64), '#ffffff00')
        draw = ImageDraw.Draw(image)
        draw.ellipse((4, 4, 60, 60), fill='#526874')
        draw.rounded_rectangle((26, 14, 38, 38), 6, fill='white')
        draw.arc((19, 23, 45, 47), 0, 180, fill='white', width=4)
        draw.line((32, 46, 32, 53), fill='white', width=4)
        if state in ('录音中', '已暂停', '需处理'):
            badge = '#3b9b94' if state == '录音中' else '#b88c3a'
            draw.ellipse((45, 45, 59, 59), fill='#526874' if state == '已暂停' else badge, outline=badge, width=3)
        return image

    def start(self):
        def run_tray():
            try:
                self.icon.run(lambda icon: (setattr(icon, 'visible', True), self.ready.set()))
            except Exception as exc:
                self.post(lambda message=str(exc): self.report('托盘不可用：' + message))
        threading.Thread(target=run_tray, daemon=True).start()
        self.thread = threading.Thread(target=self._hotkeys, daemon=True)
        self.thread.start()
        return self.ready.wait(3)

    def _hotkeys(self):
        user = ctypes.windll.user32
        self.hotkey_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        registered = []
        try:
            for key_id, letter in [(1, 'R'), (2, 'M')]:
                if user.RegisterHotKey(None, key_id, 0x0001 | 0x4000, ord(letter)):
                    registered.append(key_id)
                else:
                    self.post(lambda key=letter: self.report(f'Alt+{key} 已被占用，请使用托盘菜单。'))
            self.hotkey_ready.set()
            message = wintypes.MSG()
            while user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == 0x0312:
                    self.post(self.toggle if message.wParam == 1 else self.mark)
        finally:
            self.hotkey_ready.set()
            for key_id in registered:
                user.UnregisterHotKey(None, key_id)

    def update(self, state):
        if state != self.state:
            self.state = state
            self.icon.title = 'WaveGrab · ' + state
            self.icon.icon = self._image(state)

    def set_detail(self, text, error=False):
        self.icon.title = ('WaveGrab · ' + self.state + ' · ' + text)[:127]
        if error:
            self.icon.icon = self._image('需处理')

    def stop(self):
        if self.thread:
            self.hotkey_ready.wait(2)
            if self.hotkey_thread_id:
                ctypes.windll.user32.PostThreadMessageW(self.hotkey_thread_id, 0x0012, 0, 0)
            self.thread.join(timeout=2)
        self.icon.stop()
