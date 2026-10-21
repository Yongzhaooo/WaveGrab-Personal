"""Main application window."""

import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path
import threading
import os
import queue
import json
from handoff import clipboard_prompt

import numpy as np

from paths import get_base_path, get_src_path
import sys
sys.path.insert(0, str(get_src_path()))

from devices import AudioDevice, get_devices, get_default_devices, get_system_sources
from config import AppConfig, load_config, save_config
from visuals import window_status, write_review
from meeting import MeetingScene, detect_scene
from .widgets import WaveformCanvas, LevelMeter, OverlayProgress, COLORS, apply_light_theme
from .transcripts import TranscriptPanel
from .recordings import RecordingsPanel
from .controller import RecordingController, RecordingCallbacks, RecordingState


class AudioRecorderApp:
    """Main GUI application."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("WaveGrab · Personal")
        self._ui_queue = queue.SimpleQueue()
        self._closing = False
        self._last_error = ''
        self.desktop = None
        self.indicator = None
        self._start_pending = None
        self._start_serial = 0
        self._scene_busy = False
        self._recording_detail = ''
        self._screen_windows = []
        self.root.geometry("940x670")

        # Window icon
        icon_path = get_base_path() / "assets" / "icon_bmp.ico"
        if icon_path.exists():
            self.root.iconbitmap(str(icon_path))
        self.root.minsize(820, 640)
        self.root.resizable(True, True)

        # Load configuration
        self.config = load_config()

        # Apply dark theme
        apply_light_theme(self.root)

        # Load devices
        devices = get_devices()
        self.loopback_devices = get_system_sources(devices)
        self.input_devices = [d for d in devices if not d.is_loopback]

        # Controller
        self.controller = RecordingController(RecordingCallbacks(
            on_state_change=self._on_state_change,
            on_time_update=self._on_time_update,
            on_audio_chunk=self._on_audio_chunk,
            on_loopback_level=self._on_loopback_level,
            on_mic_level=self._on_mic_level,
            on_error=self._on_error,
            on_recording_saved=self._on_recording_saved,
            on_visuals_complete=self._on_visuals_complete
        ))

        # UI variables
        self.loopback_var = tk.StringVar()
        self.mic_var = tk.StringVar()
        self.room_mode_var = tk.BooleanVar(value=self.config.room_mode)
        self.auto_mode_var = tk.BooleanVar(value=self.config.auto_mode)
        self.screenshots_var = tk.BooleanVar(value=self.config.screenshots_enabled)
        self.screen_window_var = tk.StringVar(value='开始录音时自动识别会议窗口')
        self.screen_status_var = tk.StringVar(value='只截所选窗口；最小化时暂停截图，录音继续')
        self.loopback_vol_var = tk.DoubleVar(value=self.config.loopback_volume * 100)
        self.mic_vol_var = tk.DoubleVar(value=self.config.mic_volume * 100)
        self.output_folder_var = tk.StringVar(value=self.config.output_folder or str(Path.home() / 'Music' / 'WaveGrab'))
        self.filename_var = tk.StringVar(value=self.config.last_filename)
        self.status_var = tk.StringVar(value="就绪")
        self.time_var = tk.StringVar(value="00:00:00")

        # Mini mode state
        self._mini_mode = False
        self._normal_geometry = None

        # Create UI
        self._create_ui()

        # Save progress stays inside the existing window.
        self._overlay = OverlayProgress(self.root, "正在保存录音…")

        # Restore selections
        self._restore_device_selection()
        self._on_room_mode_change()

        if self.config.last_session and Path(self.config.last_session).is_dir():
            self.result_panel.set_folder(Path(self.config.last_session))

        # Bind close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Update preview periodically
        self._update_preview()
        self._drain_ui()

    def _post(self, callback):
        self._ui_queue.put(callback)

    def _drain_ui(self):
        for _ in range(100):
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            callback()
        try:
            if self.root.winfo_exists():
                self.root.after(40, self._drain_ui)
        except tk.TclError:
            pass

    def _create_ui(self):
        self._main_frame = ttk.Frame(self.root, padding=8)
        self._main_frame.pack(fill='both', expand=True)
        top = ttk.Frame(self._main_frame)
        top.pack(fill='x', pady=(0, 4))
        ttk.Label(top, text='WaveGrab', style='Brand.TLabel').pack(side='left')
        ttk.Label(top, text='把会议留下来', style='Muted.TLabel').pack(side='left', padx=14)
        ttk.Button(top, text='隐藏到托盘', command=self._hide_window).pack(side='right')
        self.tabs = ttk.Notebook(self._main_frame)
        self.tabs.pack(fill='both', expand=True)
        page = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(page, text='  录音  ')
        self.result_panel = TranscriptPanel(self.tabs, self._post,
            lambda: self.controller.last_session if self.controller.state in (
                RecordingState.RECORDING, RecordingState.PAUSED, RecordingState.SAVING) else None)
        self.tabs.add(self.result_panel, text='  转录与说话人  ')
        self.recordings_panel = RecordingsPanel(self.tabs, lambda: self.output_folder_var.get(), self._open_transcript)
        self.tabs.insert(1, self.recordings_panel, text='  录音记录  ')
        self.tabs.bind('<<NotebookTabChanged>>', self._on_tab_changed)
        title_row = ttk.Frame(page)
        title_row.pack(fill='x', pady=(0, 4))
        ttk.Label(title_row, text='主题', width=9).pack(side='left')
        ttk.Entry(title_row, textvariable=self.filename_var).pack(side='left', fill='x', expand=True)
        self.filename_var.trace_add('write', lambda *_: self._update_preview())
        modes = ttk.Frame(page)
        modes.pack(fill='x')
        self.auto_mode_check = ttk.Checkbutton(modes, text='自动识别 Teams 会议',
            variable=self.auto_mode_var, command=self._on_room_mode_change)
        self.auto_mode_check.pack(side='left', padx=(0, 18))
        self.room_mode_check = ttk.Checkbutton(modes, text='会议室模式 · 只录麦克风',
            variable=self.room_mode_var, command=self._on_room_mode_change)
        self.room_mode_check.pack(side='left')
        self.mode_hint = ttk.Label(page, text='', style='Muted.TLabel', wraplength=780)
        self.mode_hint.pack(anchor='w', pady=(2, 4))
        devices = ttk.Frame(page)
        devices.pack(fill='x')
        self._loopback_display_names = ['(不录制)'] + [f'{d.name} [{d.sample_rate}Hz]' for d in self.loopback_devices]
        self._mic_display_names = ['(不录制)'] + [f'{d.name} [{d.sample_rate}Hz]' for d in self.input_devices]
        mic_row = ttk.Frame(devices)
        mic_row.pack(fill='x')
        ttk.Label(mic_row, text='麦克风', width=9).pack(side='left')
        self.mic_combo = ttk.Combobox(mic_row, textvariable=self.mic_var,
            values=self._mic_display_names, state='readonly', width=45)
        self.mic_combo.pack(side='left', fill='x', expand=True, padx=(0, 12))
        self.mic_combo.current(0)
        self.mic_combo.bind('<<ComboboxSelected>>', self._on_mic_change)
        self.mic_meter = LevelMeter(mic_row, width=100, height=18)
        self.mic_meter.pack(side='left')
        gain_row = ttk.Frame(devices)
        gain_row.pack(fill='x', pady=(2, 4))
        ttk.Label(gain_row, text='录制音量', width=9).pack(side='left')
        ttk.Scale(gain_row, from_=0, to=100, variable=self.mic_vol_var,
            command=self._on_mic_vol_change, length=170).pack(side='left')
        self.mic_vol_label = ttk.Label(gain_row, width=7)
        self.mic_vol_label.pack(side='left', padx=8)
        self.test_btn = ttk.Button(gain_row, text='检查输入', command=self._on_test)
        self.test_btn.pack(side='right')
        self._system_row = ttk.Frame(devices)
        self._system_row.pack(fill='x', pady=(0, 8))
        ttk.Label(self._system_row, text='系统声音', width=9).grid(row=0, column=0, sticky='w')
        self.loopback_combo = ttk.Combobox(self._system_row, textvariable=self.loopback_var,
            values=self._loopback_display_names, state='readonly', width=45)
        self.loopback_combo.grid(row=0, column=1, sticky='ew', padx=(0, 12))
        self.loopback_combo.current(0)
        self.loopback_combo.bind('<<ComboboxSelected>>', self._on_loopback_change)
        self.loopback_meter = LevelMeter(self._system_row, width=100, height=18)
        self.loopback_meter.grid(row=0, column=2)
        ttk.Scale(self._system_row, from_=0, to=100, variable=self.loopback_vol_var,
            command=self._on_loopback_vol_change).grid(row=1, column=1, sticky='ew', pady=(8, 0))
        self.loopback_vol_label = ttk.Label(self._system_row, width=7)
        self.loopback_vol_label.grid(row=1, column=2)
        self._system_row.columnconfigure(1, weight=1)
        self._on_mic_vol_change(None)
        self._on_loopback_vol_change(None)
        screen_row = ttk.Frame(page)
        screen_row.pack(fill='x', pady=(4, 0))
        self.screen_check = ttk.Checkbutton(screen_row, text='Teams 截图 · 3 秒/张', variable=self.screenshots_var)
        self.screen_check.pack(side='left')
        self.screen_combo = ttk.Combobox(screen_row, textvariable=self.screen_window_var, state='readonly', width=35)
        self.screen_combo.pack(side='left', fill='x', expand=True, padx=8)
        self.screen_combo.bind('<<ComboboxSelected>>', lambda _: self.screenshots_var.set(True))
        self.screen_refresh = ttk.Button(screen_row, text='刷新窗口', command=self._refresh_windows)
        self.screen_refresh.pack(side='right')
        ttk.Label(page, textvariable=self.screen_status_var, style='Muted.TLabel').pack(anchor='w', pady=(2, 0))
        center = ttk.Frame(page)
        center.pack(fill='x', pady=(4, 2))
        self._timer_label = ttk.Label(center, textvariable=self.time_var, font=('Consolas', 22))
        self._timer_label.pack(side='left')
        controls = ttk.Frame(center)
        controls.pack(side='right', pady=6)
        self.rec_btn = ttk.Button(controls, text='开始录音', style='Accent.TButton', command=self._on_rec, width=10)
        self.rec_btn.pack(side='left', padx=5)
        self.pause_btn = ttk.Button(controls, text='暂停', command=self._on_pause, width=6, state='disabled')
        self.pause_btn.pack(side='left', padx=5)
        self.stop_btn = ttk.Button(controls, text='停止保存', command=self._on_stop, width=9, state='disabled')
        self.stop_btn.pack(side='left', padx=5)
        self.mini_btn = ttk.Button(controls, text='Mini', command=self._toggle_mini_mode, width=6, state='disabled')
        self.mini_btn.pack(side='left', padx=5)
        self.mark_btn = ttk.Button(controls, text='打标 Alt+M', command=self._add_marker, state='disabled')
        self.mark_btn.pack(side='left', padx=5)
        ttk.Label(page, text='Alt+R 开始 / 停止   ·   Alt+M 打标   ·   关闭窗口后驻留托盘', style='Muted.TLabel').pack(anchor='w')
        ttk.Label(page, textvariable=self.status_var, style='Muted.TLabel').pack(anchor='w', pady=4)
        footer = ttk.Frame(page)
        footer.pack(fill='x')
        ttk.Separator(footer).pack(fill='x', pady=4)
        folder = ttk.Frame(footer)
        folder.pack(fill='x')
        ttk.Label(folder, text='保存到', width=9).pack(side='left')
        ttk.Entry(folder, textvariable=self.output_folder_var).pack(side='left', fill='x', expand=True, padx=(0, 10))
        ttk.Button(folder, text='选择', command=self._browse_folder).pack(side='right')
        actions = ttk.Frame(footer)
        actions.pack(fill='x', pady=(8, 0))
        ttk.Button(actions, text='打开最近录音', command=self._open_recordings).pack(side='left')
        ttk.Button(actions, text='复制交接说明', command=self._copy_handoff).pack(side='left', padx=8)
        ttk.Button(actions, text='回看画面与标记', command=self._open_review).pack(side='left')
        ttk.Button(actions, text='查看文字 →', command=lambda: self.tabs.select(self.result_panel)).pack(side='right')

    def _restore_device_selection(self) -> None:
        """Restore device selections from config."""
        # Loopback - search by name and sample rate
        if self.config.loopback_device:
            saved_name = self.config.loopback_device
            saved_rate = self.config.loopback_sample_rate
            for i, d in enumerate(self.loopback_devices):
                # Match by name (exact or contained) and sample rate if available
                name_match = (d.name == saved_name) or (d.name in saved_name)
                rate_match = (saved_rate == 0) or (d.sample_rate == saved_rate)
                if name_match and rate_match:
                    self.loopback_var.set(self._loopback_display_names[i + 1])
                    self._on_loopback_change(None)
                    break

        if self.loopback_var.get() == '(不录制)' and self.loopback_devices:
            defaults = get_default_devices()
            selected = next((i for i, d in enumerate(self.loopback_devices) if d.index == defaults[0]), 0)
            self.loopback_var.set(self._loopback_display_names[selected + 1])
            self._on_loopback_change(None)
            if self.config.loopback_device:
                self.status_var.set('之前的系统声音设备不可用，已选择当前默认设备')
        if not self.config.mic_device and self.input_devices:
            defaults = get_default_devices()
            selected = next((i for i, d in enumerate(self.input_devices) if d.index == defaults[1]), 0)
            self.mic_var.set(self._mic_display_names[selected + 1])
            self._on_mic_change(None)

        # Microphone - search by name and sample rate
        if self.config.mic_device:
            saved_name = self.config.mic_device
            saved_rate = self.config.mic_sample_rate
            for i, d in enumerate(self.input_devices):
                # Match by name (exact or contained) and sample rate if available
                name_match = (d.name == saved_name) or (d.name in saved_name)
                rate_match = (saved_rate == 0) or (d.sample_rate == saved_rate)
                if name_match and rate_match:
                    self.mic_var.set(self._mic_display_names[i + 1])
                    self._on_mic_change(None)
                    break

        if self.mic_var.get() == '(不录制)' and self.input_devices:
            defaults = get_default_devices()
            selected = next((i for i, d in enumerate(self.input_devices) if d.index == defaults[1]), 0)
            self.mic_var.set(self._mic_display_names[selected + 1])
            self._on_mic_change(None)
            self.status_var.set('之前的麦克风不可用，已选择当前默认设备')

    def _update_preview(self):
        self.controller.set_filename_prefix(self.filename_var.get())

    def _on_room_mode_change(self):
        if not self.controller.set_room_mode(self.room_mode_var.get()):
            self.room_mode_var.set(self.controller.room_mode)
            return
        room = self.controller.room_mode
        automatic = self.auto_mode_var.get()
        self.room_mode_check.configure(state='disabled' if automatic else 'normal')
        self.loopback_combo.configure(state='readonly' if automatic or not room else 'disabled')
        if room and not automatic:
            self._system_row.pack_forget()
        else:
            self._system_row.pack(fill='x', pady=(0, 8))
        self.mode_hint.configure(text=(
            '默认录麦克风；确认 Teams 会议正在使用所选虚拟声卡时，自动录双路及会议窗口。' if automatic else
            '录会议室里的声音；不播放音频，不改变 Teams 静音或 No audio 设置。' if room else
            '录系统输出或虚拟声卡输入，加上实际麦克风；不回放声音。'))

    def _browse_folder(self) -> None:
        """Open folder selection dialog."""
        folder = filedialog.askdirectory(
            initialdir=self.output_folder_var.get(),
            title="选择录音文件夹"
        )
        if folder:
            self.output_folder_var.set(folder)
            self.controller.set_output_folder(folder)

    def _on_loopback_change(self, event) -> None:
        """Handle loopback device change."""
        display_name = self.loopback_var.get()
        if display_name == "(不录制)":
            self.controller.set_loopback_device(None)
        else:
            # Find device by index in list
            idx = self._loopback_display_names.index(display_name) - 1  # -1 for "(不录制)"
            if 0 <= idx < len(self.loopback_devices):
                self.controller.set_loopback_device(self.loopback_devices[idx])

    def _on_mic_change(self, event) -> None:
        """Handle microphone device change."""
        display_name = self.mic_var.get()
        if display_name == "(不录制)":
            self.controller.set_mic_device(None)
        else:
            # Find device by index in list
            idx = self._mic_display_names.index(display_name) - 1  # -1 for "(不录制)"
            if 0 <= idx < len(self.input_devices):
                self.controller.set_mic_device(self.input_devices[idx])

    def _on_loopback_vol_change(self, event) -> None:
        """Handle loopback volume change."""
        vol = self.loopback_vol_var.get()
        self.loopback_vol_label.configure(text=f"{int(vol)}%")
        self.controller.set_loopback_volume(vol / 100.0)

    def _on_mic_vol_change(self, event) -> None:
        """Handle microphone volume change."""
        vol = self.mic_vol_var.get()
        self.mic_vol_label.configure(text=f"{int(vol)}%")
        self.controller.set_mic_volume(vol / 100.0)

    def _toggle_mini_mode(self) -> None:
        """Toggle between normal and mini mode."""
        if self._mini_mode:
            self._exit_mini_mode()
        else:
            self._enter_mini_mode()

    def _create_mini_frame(self) -> None:
        """Create mini mode frame."""
        self._mini_frame = ttk.Frame(self.root, padding=5)

        # Mini waveform
        self._mini_waveform = WaveformCanvas(self._mini_frame, width=80, height=25, history_size=40)
        self._mini_waveform.pack(side=tk.LEFT, padx=(0, 10))

        # Mini timer
        self._mini_timer = ttk.Label(self._mini_frame, textvariable=self.time_var, font=("Consolas", 11))
        self._mini_timer.pack(side=tk.LEFT, padx=(0, 10))

        # Mini buttons
        self._mini_pause_btn = ttk.Button(self._mini_frame, text="||", command=self._on_pause, width=3)
        self._mini_pause_btn.pack(side=tk.LEFT, padx=2)

        self._mini_stop_btn = ttk.Button(self._mini_frame, text="■", command=self._on_stop, width=3)
        self._mini_stop_btn.pack(side=tk.LEFT, padx=2)

        # Expand button
        self._mini_expand_btn = ttk.Button(self._mini_frame, text="+", command=self._toggle_mini_mode, width=3)
        self._mini_expand_btn.pack(side=tk.LEFT, padx=(10, 0))

    def _enter_mini_mode(self) -> None:
        """Enter mini mode."""
        self._mini_mode = True
        self._normal_geometry = self.root.geometry()

        # Create mini frame if not exists
        if not hasattr(self, '_mini_frame'):
            self._create_mini_frame()

        # Hide main frame
        self._main_frame.pack_forget()

        # Show mini frame
        self._mini_frame.pack(fill=tk.X)

        # Sync button state
        if self.controller.state == RecordingState.PAUSED:
            self._mini_pause_btn.configure(text="▶")
        else:
            self._mini_pause_btn.configure(text="||")

        # Always on top and resize
        self.root.attributes("-topmost", True)
        self.root.geometry("280x45")
        self.root.minsize(250, 40)
        self.root.resizable(False, False)

    def _exit_mini_mode(self) -> None:
        """Exit mini mode."""
        self._mini_mode = False

        # Remove always on top
        self.root.attributes("-topmost", False)

        # Hide mini frame
        self._mini_frame.pack_forget()

        # Show main frame
        self._main_frame.pack(fill=tk.BOTH, expand=True)

        # Restore size
        self.root.resizable(True, True)
        self.root.minsize(820, 640)
        if self._normal_geometry:
            self.root.geometry(self._normal_geometry)
        else:
            self.root.geometry("940x670")

    def _on_test(self) -> None:
        """Start/stop device test."""
        if self.controller.state == RecordingState.MONITORING:
            self.controller.stop_monitoring()
            self.test_btn.configure(text="检查输入")
            self.status_var.set("就绪")
        else:
            if self.controller.start_monitoring():
                self.test_btn.configure(text="停止检查")
                self.status_var.set("正在检查输入，不播放声音")
            else:
                self._report_error('请至少选择一个可用录音设备')

    def _on_rec(self) -> None:
        """Start recording."""
        if self.controller.state not in (RecordingState.IDLE, RecordingState.MONITORING):
            return
        if self._start_pending is not None:
            return
        if self.controller.state == RecordingState.MONITORING:
            self.controller.stop_monitoring()
        if self.auto_mode_var.get():
            self._start_serial += 1
            token = self._start_serial
            self._start_pending = token
            self.rec_btn.configure(state='disabled')
            self.status_var.set('准备录音 · 正在识别会议')
            if self.indicator:
                self.indicator.update('准备中')
            self._scan_scene(lambda scene: self._finish_auto_start(token, scene))
            self.root.after(2500, lambda: self._finish_auto_start(token,
                MeetingScene(detail='会议识别超时 · 已使用会议室模式')))
        else:
            self._start_recording()

    def _finish_auto_start(self, token, scene):
        if self._closing or self._start_pending != token:
            return
        self._start_pending = None
        if not self.auto_mode_var.get():
            self._start_recording()
            return
        self._set_scene_windows(scene)
        self.room_mode_var.set(not (scene.target and scene.virtual_audio))
        self._on_room_mode_change()
        self._start_recording(scene)

    def _start_recording(self, scene=None):
        self.controller.set_output_folder(self.output_folder_var.get())
        self.controller.set_filename_prefix(self.filename_var.get())
        self.controller.screen_target = None
        self._recording_detail = scene.detail if scene else ('会议室模式' if self.room_mode_var.get() else '手动双路')
        if self.screenshots_var.get():
            if scene is not None:
                target = scene.target if scene.virtual_audio else None
            else:
                index = self.screen_combo.current()
                target = self._screen_windows[index] if 0 <= index < len(self._screen_windows) else None
            reason = window_status(target) if target else ''
            if target and not reason:
                self.controller.screen_target = target
            elif target:
                self._recording_detail += ' · ' + reason + '，仅录音'

        self._last_error = ''
        if self.controller.start_recording():
            self.test_btn.configure(text="检查输入", state=tk.DISABLED)
            self.status_var.set('录音中 · ' + self._recording_detail)
            self._save_config()
            if self.desktop:
                self.desktop.set_detail('Alt+M 打标，Alt+R 停止')
        else:
            self.rec_btn.configure(state='normal')
            if self.indicator:
                self.indicator.update('就绪')
                self.indicator.flash('error')

    def _on_pause(self) -> None:
        """Pause or resume recording."""
        if self.controller.state == RecordingState.RECORDING:
            self.controller.pause_recording()
        elif self.controller.state == RecordingState.PAUSED:
            self.controller.resume_recording()

    def _on_stop(self) -> None:
        """Stop recording."""
        if not self.controller.is_recording:
            return
        self.stop_btn.configure(state=tk.DISABLED)
        self.pause_btn.configure(state=tk.DISABLED)
        # Show immediate visual feedback
        self.root.configure(cursor="wait")
        self._overlay.show()
        self.root.update()

        # Stop in background to not block UI
        def stop_async():
            self.controller.stop_recording()
            self._post(lambda: self.root.configure(cursor=""))

        threading.Thread(target=stop_async, daemon=True).start()

    def _on_state_change(self, state: RecordingState) -> None:
        """Callback for state change."""
        self._post(lambda: self._update_ui_state(state))

    def _update_ui_state(self, state: RecordingState) -> None:
        """Update UI based on state."""
        idle = state == RecordingState.IDLE
        self.auto_mode_check.configure(state='normal' if idle else 'disabled')
        self.screen_check.configure(state='normal' if idle else 'disabled')
        self.screen_combo.configure(state='readonly' if idle else 'disabled')
        self.screen_refresh.configure(state='normal' if idle else 'disabled')
        self.mark_btn.configure(state='normal' if state in (RecordingState.RECORDING, RecordingState.PAUSED) else 'disabled')
        if self.desktop:
            self.desktop.update({RecordingState.IDLE: '就绪', RecordingState.RECORDING: '录音中',
                RecordingState.PAUSED: '已暂停', RecordingState.MONITORING: '检查输入',
                RecordingState.SAVING: '保存中'}[state])
        if self.indicator:
            self.indicator.update({RecordingState.IDLE: '就绪', RecordingState.RECORDING: '录音中',
                RecordingState.PAUSED: '已暂停', RecordingState.MONITORING: '检查输入',
                RecordingState.SAVING: '保存中'}[state])
        self.room_mode_check.configure(state='normal' if idle and not self.auto_mode_var.get() else 'disabled')
        self.mic_combo.configure(state='readonly' if state == RecordingState.IDLE else 'disabled')
        self.loopback_combo.configure(state='readonly' if idle and (self.auto_mode_var.get() or not self.room_mode_var.get()) else 'disabled')
        if state == RecordingState.IDLE:
            self.screen_status_var.set('只截所选窗口；最小化时暂停截图，录音继续')
            self._overlay.hide()
            self.rec_btn.configure(state=tk.NORMAL, text="  开始录音")
            self.pause_btn.configure(state=tk.DISABLED, text="  暂停")
            self.stop_btn.configure(state=tk.DISABLED)
            self.test_btn.configure(state=tk.NORMAL, text="检查输入")
            self.mini_btn.configure(state=tk.DISABLED)
            self.status_var.set("就绪")
            self.loopback_meter.clear()
            self.mic_meter.clear()
            self.time_var.set("00:00:00")
            # Exit mini mode if active
            if self._mini_mode:
                self._exit_mini_mode()

        elif state == RecordingState.MONITORING:
            self.rec_btn.configure(state=tk.NORMAL)
            self.pause_btn.configure(state=tk.DISABLED)
            self.stop_btn.configure(state=tk.DISABLED)
            self.test_btn.configure(state=tk.NORMAL, text="停止检查")
            self.mini_btn.configure(state=tk.DISABLED)
            self.status_var.set("正在检查输入，不播放声音")

        elif state == RecordingState.RECORDING:
            self.rec_btn.configure(state=tk.DISABLED)
            self.pause_btn.configure(state=tk.NORMAL, text="  暂停")
            self.stop_btn.configure(state=tk.NORMAL)
            self.test_btn.configure(state=tk.DISABLED, text="检查输入")
            self.mini_btn.configure(state=tk.NORMAL)
            self.status_var.set('录音中 · ' + self._recording_detail)
            if hasattr(self, '_mini_pause_btn'):
                self._mini_pause_btn.configure(text="||")

        elif state == RecordingState.PAUSED:
            self.rec_btn.configure(state=tk.DISABLED)
            self.pause_btn.configure(state=tk.NORMAL, text="  继续")
            self.stop_btn.configure(state=tk.NORMAL)
            self.test_btn.configure(state=tk.DISABLED)
            self.mini_btn.configure(state=tk.NORMAL)
            self.status_var.set("已暂停")
            if hasattr(self, '_mini_pause_btn'):
                self._mini_pause_btn.configure(text="▶")

        elif state == RecordingState.SAVING:
            self.rec_btn.configure(state=tk.DISABLED)
            self.pause_btn.configure(state=tk.DISABLED)
            self.stop_btn.configure(state=tk.DISABLED)
            self.test_btn.configure(state=tk.DISABLED)
            self.mini_btn.configure(state=tk.DISABLED)
            self.status_var.set("正在保存录音…")

    def _on_time_update(self, elapsed: float) -> None:
        """Callback for time update."""
        self._post(lambda: self._update_time(elapsed))

    def _update_time(self, elapsed: float) -> None:
        """Update time display."""
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        self.time_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        screens = self.controller.screens
        if screens:
            self.screen_status_var.set('录音与截图已暂停' if self.controller.state == RecordingState.PAUSED
                                       else screens.poll_status())

    def _on_audio_chunk(self, chunk: np.ndarray | None) -> None:
        """Callback for audio chunk (during recording)."""
        def update():
            if hasattr(self, '_mini_waveform'):
                self._mini_waveform.update_waveform(chunk)
        self._post(update)

    def _on_loopback_level(self, chunk: np.ndarray | None) -> None:
        """Callback for loopback level (during monitoring)."""
        self._post(lambda: self.loopback_meter.update_from_audio(chunk))

    def _on_mic_level(self, chunk: np.ndarray | None) -> None:
        """Callback for microphone level (during monitoring)."""
        self._post(lambda: self.mic_meter.update_from_audio(chunk))

    def _on_error(self, message: str) -> None:
        """Callback for errors."""
        self._post(lambda: self._report_error(message))

    def _report_error(self, message):
        self._last_error = message
        self.status_var.set(message)
        if self.desktop:
            self.desktop.set_detail(message, error=True)
        if self.indicator:
            self.indicator.flash('error')

    def _on_recording_saved(self, path: Path) -> None:
        """Audio is closed and available independently of optional processing."""
        self._post(lambda: self._show_completion(path))

    def _on_visuals_complete(self, result):
        path, error = result
        def update():
            if self.controller.state != RecordingState.IDLE or self._latest_folder() != path:
                return
            if error:
                self._report_error(f'{path.name}：{error}')
            elif not self._last_error:
                self.status_var.set(f'录音已保存，回看页已就绪：{path.name}')
        self._post(update)

    def _show_completion(self, path: Path) -> None:
        """Show completion message."""
        if not self.result_panel.busy:
            self.result_panel.set_folder(path)
        self.config.last_session = str(path)
        self._save_config()
        if self.tabs.select() == str(self.recordings_panel):
            self.recordings_panel.refresh()
        if self._last_error:
            self._report_error(self._last_error)
        else:
            self.status_var.set(f"已保存：{path.name}")
        if self.desktop and not self._last_error:
            self.desktop.set_detail('录音已保存 · 回看页在后台准备')

    def _save_config(self) -> None:
        """Save current configuration."""
        self.config.room_mode = self.room_mode_var.get()
        self.config.auto_mode = self.auto_mode_var.get()
        self.config.screenshots_enabled = self.screenshots_var.get()
        display_loopback = self.loopback_var.get()
        display_mic = self.mic_var.get()

        # Save device name and sample rate
        if display_loopback != "(不录制)":
            try:
                idx = self._loopback_display_names.index(display_loopback) - 1
                device = self.loopback_devices[idx]
                self.config.loopback_device = device.name
                self.config.loopback_sample_rate = device.sample_rate
            except (ValueError, IndexError):
                self.config.loopback_device = ""
                self.config.loopback_sample_rate = 0
        else:
            self.config.loopback_device = ""
            self.config.loopback_sample_rate = 0

        if display_mic != "(不录制)":
            try:
                idx = self._mic_display_names.index(display_mic) - 1
                device = self.input_devices[idx]
                self.config.mic_device = device.name
                self.config.mic_sample_rate = device.sample_rate
            except (ValueError, IndexError):
                self.config.mic_device = ""
                self.config.mic_sample_rate = 0
        else:
            self.config.mic_device = ""
            self.config.mic_sample_rate = 0

        self.config.loopback_volume = self.loopback_vol_var.get() / 100.0
        self.config.mic_volume = self.mic_vol_var.get() / 100.0
        self.config.output_folder = self.output_folder_var.get()
        self.config.last_filename = self.filename_var.get()

        save_config(self.config)

    def _on_tab_changed(self, _=None):
        if self.tabs.select() == str(self.recordings_panel):
            self.recordings_panel.refresh()
        elif self.recordings_panel.folder:
            self.recordings_panel.save(refresh_people=False)
        if self.tabs.select() == str(self.result_panel) and self.result_panel.data and not self.result_panel.busy:
            self.result_panel.reload()

    def _open_transcript(self, folder):
        if self.result_panel.busy:
            self.recordings_panel.status.set('另一段录音正在转录，请等待完成或先取消。')
            return
        self.result_panel.set_folder(folder)
        self.tabs.select(self.result_panel)

    def _latest_folder(self):
        return self.controller.last_session or (Path(self.config.last_session) if self.config.last_session else None)

    def _open_recordings(self):
        folder = self._latest_folder() or Path(self.output_folder_var.get())
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        except OSError as exc:
            self._on_error(str(exc))

    def _copy_handoff(self):
        if self.controller.is_recording or self.controller.state == RecordingState.SAVING:
            self.status_var.set('请先停止并保存录音')
            return
        folder = self._latest_folder()
        if not folder or not (folder / 'HANDOFF.md').exists():
            self.status_var.set('先完成一次录音，再复制交接说明')
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(clipboard_prompt(folder))
        self.status_var.set('已复制，可粘贴给 Codex、agy 或其他工具')

    def _refresh_windows(self):
        if self.controller.state != RecordingState.IDLE:
            return
        self.screen_status_var.set('正在识别 Teams 通话窗口…')
        self._scan_scene(self._set_scene_windows)

    def _scan_scene(self, complete):
        if self._scene_busy:
            complete(MeetingScene(detail='会议识别尚未完成 · 会议室模式'))
            return
        self._scene_busy = True
        index = self.loopback_combo.current() - 1
        capture_name = self.loopback_devices[index].name if 0 <= index < len(self.loopback_devices) else ''
        def scan():
            try:
                scene = detect_scene(capture_name)
            except Exception as exc:
                scene = MeetingScene(detail='会议识别不可用 · 会议室模式：' + str(exc))
            self._post(lambda: deliver(scene))
        def deliver(scene):
            self._scene_busy = False
            if not self._closing:
                current = self.loopback_combo.current() - 1
                selected = self.loopback_devices[current].name if 0 <= current < len(self.loopback_devices) else ''
                if selected != capture_name:
                    scene = MeetingScene(detail='识别期间声音设备已改变 · 会议室模式')
                complete(scene)
        threading.Thread(target=scan, daemon=True).start()

    def _set_scene_windows(self, scene):
        self._screen_windows = scene.windows
        self.screen_combo.configure(values=[w.title for w in self._screen_windows])
        if scene.target:
            self.screen_combo.current(0)
        else:
            self.screen_window_var.set('请选择会议窗口' if scene.windows else '没有确认的 Teams 会议窗口')
        self.screen_status_var.set(scene.detail)

    def _toggle_recording(self):
        if self._start_pending is not None:
            self._start_pending = None
            self.rec_btn.configure(state='normal')
            self.status_var.set('已取消开始录音')
            if self.indicator:
                self.indicator.update('就绪')
        elif self.controller.is_recording:
            self._on_stop()
        elif self.controller.state == RecordingState.IDLE:
            self._on_rec()

    def _add_marker(self):
        try:
            marker = self.controller.add_marker()
            if marker:
                text = f"{marker['label']} · {int(marker['seconds']) // 60:02d}:{int(marker['seconds']) % 60:02d}"
                self.status_var.set(text)
                if self.desktop:
                    self.desktop.set_detail(text)
                if self.indicator:
                    self.indicator.flash('marker')
            else:
                self.status_var.set('录音开始后可打标')
                if self.indicator:
                    self.indicator.flash('error')
        except OSError as exc:
            self._report_error(f'标记未保存：{exc}')

    def _open_review(self):
        folder = self.result_panel.folder or self._latest_folder()
        if folder and (folder / 'review.html').is_file():
            os.startfile(folder / 'review.html')
        elif folder and (folder / 'timeline.jsonl').is_file():
            metadata = folder / 'session.json'
            try:
                if not metadata.exists() or json.loads(metadata.read_text(encoding='utf-8')).get('status') == 'recording':
                    self._report_error('这一场仍在录制，请先停止保存。')
                    return
            except (OSError, ValueError) as exc:
                self._report_error(str(exc))
                return
            self.status_var.set('正在后台生成回看页；可以继续录音')
            def prepare():
                try:
                    write_review(folder)
                    self._post(lambda: os.startfile(folder / 'review.html'))
                except Exception as exc:
                    self._on_error(f'回看页未生成：{exc}')
            threading.Thread(target=prepare, daemon=True).start()
        else:
            self._report_error('请先停止保存一段新版录音，再打开回看页。')

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()

    def _hide_window(self):
        if self.desktop and self.desktop.ready.is_set():
            if not self.recordings_panel.save(refresh_people=False):
                return
            self._save_config()
            self.root.withdraw()

    def _on_close(self):
        if self.desktop and self.desktop.ready.is_set():
            self._hide_window()
        else:
            self._exit()

    def _exit(self):
        if self._closing:
            return
        self.recordings_panel.save(refresh_people=False)
        if self.result_panel.busy:
            self.result_panel.cancel()
        self._closing = True
        self._start_pending = None
        if self.indicator:
            self.indicator.close()
            self.indicator = None
        self._save_config()
        def close():
            self.controller.cleanup()
            if self.desktop:
                self.desktop.stop()
            self._post(self.root.destroy)
        threading.Thread(target=close, daemon=True).start()

    def run(self) -> None:
        """Start application."""
        from desktop import DesktopControls, RecordingIndicator
        self.root.withdraw()
        self.indicator = RecordingIndicator(self.root)
        self.desktop = DesktopControls(self._post, self._show_window, self._toggle_recording,
            self._add_marker, self._open_review, self._exit, self._report_error)
        if self.desktop.start():
            self.desktop.set_detail('右键设置 · Alt+R 开始/停止，Alt+M 打标')
        else:
            self.root.deiconify()
        self.root.mainloop()
