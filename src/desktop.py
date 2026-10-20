"""Tray controls and Windows global hotkeys; all actions are posted to Tk."""
import ctypes
from ctypes import wintypes
import threading

from PIL import Image, ImageDraw
import pystray


class RecordingIndicator:
    """Small click-through status dot above the primary taskbar; never activates."""
    def __init__(self, root):
        import tkinter as tk
        self.root, self.state, self.timer = root, '就绪', None
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.title('WaveGrab · 状态')
        self.window.overrideredirect(True)
        self.window.configure(background='#010203')
        self.window.attributes('-transparentcolor', '#010203')
        self.canvas = tk.Canvas(self.window, width=20, height=20, background='#010203',
                                highlightthickness=0, takefocus=False)
        self.canvas.pack()
        self.dot = self.canvas.create_oval(5, 5, 15, 15, fill='#ce6464', outline='')
        self.window.update_idletasks()
        user = ctypes.windll.user32
        user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user.GetAncestor.restype = wintypes.HWND
        user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        user.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.hwnd = user.GetAncestor(self.window.winfo_id(), 2)
        style = user.GetWindowLongPtrW(self.hwnd, -20)
        user.SetWindowLongPtrW(self.hwnd, -20, style | 0x08000000 | 0x80 | 0x20)

    def _paint(self, color, ring=False):
        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)
        self.window.geometry(f'20x20+{max(0, rect.right - 30)}+{max(0, rect.bottom - 30)}')
        self.canvas.itemconfigure(self.dot, fill='' if ring else color, outline=color, width=2)
        self.window.deiconify()
        user = ctypes.windll.user32
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user.SetWindowPos(self.hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x13)

    def update(self, state):
        previous, self.state = self.state, state
        if self.timer:
            self.root.after_cancel(self.timer)
            self.timer = None
        if state == '录音中':
            self._paint('#ce6464')
        elif state in ('已暂停', '保存中', '准备中'):
            self._paint('#c39a48', ring=state == '已暂停')
        elif previous in ('录音中', '已暂停', '保存中'):
            self.flash('saved')
        else:
            self.window.withdraw()

    def flash(self, event):
        if self.timer:
            self.root.after_cancel(self.timer)
        self._paint('#3e9a89' if event in ('marker', 'saved') else '#c39a48', ring=event == 'marker')
        self.timer = self.root.after(1100, self._restore)

    def _restore(self):
        self.timer = None
        self.update(self.state)

    def close(self):
        if self.timer:
            self.root.after_cancel(self.timer)
            self.timer = None
        self.window.destroy()


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
            draw.ellipse((43, 43, 61, 61), fill='#df4b51' if state == '录音中' else '#d6a33b')
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
