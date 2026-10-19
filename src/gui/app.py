"""Main application window."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import threading
import os
import queue
from handoff import clipboard_prompt

import numpy as np

from paths import get_base_path, get_src_path
import sys
sys.path.insert(0, str(get_src_path()))

from devices import AudioDevice, get_devices, get_default_devices
from config import AppConfig, load_config, save_config
from .widgets import WaveformCanvas, LevelMeter, OverlayProgress, ToastNotification, COLORS, apply_light_theme
from .transcripts import TranscriptPanel
from .controller import RecordingController, RecordingCallbacks, RecordingState


class AudioRecorderApp:
    """Main GUI application."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("WaveGrab · Personal")
        self._ui_queue = queue.SimpleQueue()
        self._closing = False
        self.root.geometry("940x760")

        # Window icon
        icon_path = get_base_path() / "assets" / "icon_bmp.ico"
        if icon_path.exists():
            self.root.iconbitmap(str(icon_path))
        self.root.minsize(820, 660)
        self.root.resizable(True, True)

        # Load configuration
        self.config = load_config()

        # Apply dark theme
        apply_light_theme(self.root)

        # Load devices
        devices = get_devices()
        self.loopback_devices = [d for d in devices if d.is_loopback]
        self.input_devices = [d for d in devices if not d.is_loopback]

        # Controller
        self.controller = RecordingController(RecordingCallbacks(
            on_state_change=self._on_state_change,
            on_time_update=self._on_time_update,
            on_audio_chunk=self._on_audio_chunk,
            on_loopback_level=self._on_loopback_level,
            on_mic_level=self._on_mic_level,
            on_error=self._on_error,
            on_conversion_complete=self._on_conversion_complete
        ))

        # UI variables
        self.loopback_var = tk.StringVar()
        self.mic_var = tk.StringVar()
        self.room_mode_var = tk.BooleanVar(value=self.config.room_mode)
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

        # Overlay and toast
        self._overlay = OverlayProgress(self.root, "正在保存录音…")
        self._toast = ToastNotification(self.root)

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
        self._main_frame = ttk.Frame(self.root, padding=16)
        self._main_frame.pack(fill='both', expand=True)
        top = ttk.Frame(self._main_frame)
        top.pack(fill='x', pady=(0, 12))
        ttk.Label(top, text='WaveGrab', style='Brand.TLabel').pack(side='left')
        ttk.Label(top, text='把会议留下来', style='Muted.TLabel').pack(side='left', padx=14)
        self.tabs = ttk.Notebook(self._main_frame)
        self.tabs.pack(fill='both', expand=True)
        page = ttk.Frame(self.tabs, padding=24)
        self.tabs.add(page, text='  录音  ')
        self.result_panel = TranscriptPanel(self.tabs, self._post,
            lambda: self.controller.state == RecordingState.IDLE)
        self.tabs.add(self.result_panel, text='  转录与说话人  ')
        ttk.Label(page, text='新的会议录音', style='Title.TLabel').pack(anchor='w')
        title_row = ttk.Frame(page)
        title_row.pack(fill='x', pady=(16, 14))
        ttk.Label(title_row, text='主题', width=9).pack(side='left')
        ttk.Entry(title_row, textvariable=self.filename_var).pack(side='left', fill='x', expand=True)
        self.filename_var.trace_add('write', lambda *_: self._update_preview())
        self.room_mode_check = ttk.Checkbutton(page, text='会议室模式 · 只录麦克风',
            variable=self.room_mode_var, command=self._on_room_mode_change)
        self.room_mode_check.pack(anchor='w')
        self.mode_hint = ttk.Label(page, text='', style='Muted.TLabel', wraplength=780)
        self.mode_hint.pack(anchor='w', pady=(6, 16))
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
        gain_row.pack(fill='x', pady=(8, 12))
        ttk.Label(gain_row, text='录制音量', width=9).pack(side='left')
        ttk.Scale(gain_row, from_=0, to=100, variable=self.mic_vol_var,
            command=self._on_mic_vol_change, length=170).pack(side='left')
        self.mic_vol_label = ttk.Label(gain_row, width=7)
        self.mic_vol_label.pack(side='left', padx=8)
        self.test_btn = ttk.Button(gain_row, text='检查输入', command=self._on_test)
        self.test_btn.pack(side='right')
        self._system_row = ttk.Frame(devices)
        self._system_row.pack(fill='x', pady=(0, 12))
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
        center = ttk.Frame(page)
        center.pack(fill='both', expand=True, pady=(14, 8))
        self._timer_label = ttk.Label(center, textvariable=self.time_var, style='Timer.TLabel')
        self._timer_label.pack(pady=(0, 4))
        self.waveform = WaveformCanvas(center, height=64)
        self.waveform.pack(fill='x', pady=8)
        controls = ttk.Frame(center)
        controls.pack(pady=10)
        self.rec_btn = ttk.Button(controls, text='开始录音', style='Accent.TButton', command=self._on_rec, width=14)
        self.rec_btn.pack(side='left', padx=5)
        self.pause_btn = ttk.Button(controls, text='暂停', command=self._on_pause, width=9, state='disabled')
        self.pause_btn.pack(side='left', padx=5)
        self.stop_btn = ttk.Button(controls, text='停止保存', command=self._on_stop, width=11, state='disabled')
        self.stop_btn.pack(side='left', padx=5)
        self.mini_btn = ttk.Button(controls, text='Mini', command=self._toggle_mini_mode, width=6, state='disabled')
        self.mini_btn.pack(side='left', padx=5)
        ttk.Label(center, textvariable=self.status_var, style='Muted.TLabel').pack(pady=4)
        ttk.Separator(page).pack(fill='x', pady=12)
        folder = ttk.Frame(page)
        folder.pack(fill='x')
        ttk.Label(folder, text='保存到', width=9).pack(side='left')
        ttk.Entry(folder, textvariable=self.output_folder_var).pack(side='left', fill='x', expand=True, padx=(0, 10))
        ttk.Button(folder, text='选择', command=self._browse_folder).pack(side='right')
        actions = ttk.Frame(page)
        actions.pack(fill='x', pady=(12, 0))
        ttk.Button(actions, text='打开最近录音', command=self._open_recordings).pack(side='left')
        ttk.Button(actions, text='复制交接说明', command=self._copy_handoff).pack(side='left', padx=8)
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
        self.loopback_combo.configure(state=tk.DISABLED if room else 'readonly')
        if room:
            self._system_row.pack_forget()
        else:
            self._system_row.pack(fill='x', pady=(0, 12))
        self.mode_hint.configure(text=(
            '录会议室里的声音；不播放音频，不改变 Teams 静音或 No audio 设置。' if room else
            '录所选系统声音与麦克风；不改变 Teams 设置。'))

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
        self.root.minsize(820, 660)
        if self._normal_geometry:
            self.root.geometry(self._normal_geometry)
        else:
            self.root.geometry("940x760")

    def _on_test(self) -> None:
        """Start/stop device test."""
        if self.result_panel.busy:
            messagebox.showinfo('正在处理文字', '请先完成或取消转录。')
            return
        if self.controller.state == RecordingState.MONITORING:
            self.controller.stop_monitoring()
            self.test_btn.configure(text="检查输入")
            self.status_var.set("就绪")
        else:
            if self.controller.start_monitoring():
                self.test_btn.configure(text="停止检查")
                self.status_var.set("正在检查输入，不播放声音")
            else:
                messagebox.showwarning("Warning", "请至少选择一个录音设备")

    def _on_rec(self) -> None:
        """Start recording."""
        if self.result_panel.busy:
            messagebox.showinfo('正在处理文字', '请等转录完成或取消后再开始录音。')
            return
        self.controller.set_output_folder(self.output_folder_var.get())
        self.controller.set_filename_prefix(self.filename_var.get())

        if self.controller.start_recording():
            self.test_btn.configure(text="检查输入", state=tk.DISABLED)
            self.status_var.set("录音中…")

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
        self.room_mode_check.configure(state=tk.NORMAL if state == RecordingState.IDLE else tk.DISABLED)
        self.mic_combo.configure(state='readonly' if state == RecordingState.IDLE else 'disabled')
        self.loopback_combo.configure(state='readonly' if state == RecordingState.IDLE and not self.room_mode_var.get() else 'disabled')
        if state == RecordingState.IDLE:
            self._overlay.hide()
            self.rec_btn.configure(state=tk.NORMAL, text="  开始录音")
            self.pause_btn.configure(state=tk.DISABLED, text="  暂停")
            self.stop_btn.configure(state=tk.DISABLED)
            self.test_btn.configure(state=tk.NORMAL, text="检查输入")
            self.mini_btn.configure(state=tk.DISABLED)
            self.status_var.set("就绪")
            self.waveform.clear()
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
            self.status_var.set("录音中…")
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

        elif state == RecordingState.CONVERTING:
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

    def _on_audio_chunk(self, chunk: np.ndarray | None) -> None:
        """Callback for audio chunk (during recording)."""
        def update():
            self.waveform.update_waveform(chunk)
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
        self._post(lambda: messagebox.showerror("Error", message))

    def _on_conversion_complete(self, path: Path) -> None:
        """Callback for conversion complete."""
        self._post(lambda: self._show_completion(path))

    def _show_completion(self, path: Path) -> None:
        """Show completion message."""
        self.result_panel.set_folder(path)
        self.tabs.select(self.result_panel)
        self.config.last_session = str(path)
        self._save_config()
        self.status_var.set(f"已保存：{path.name}")
        self._toast.show("录音已保存，可复制交接说明", duration=3500)

    def _save_config(self) -> None:
        """Save current configuration."""
        self.config.room_mode = self.room_mode_var.get()
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
        if self.controller.is_recording or self.controller.state == RecordingState.CONVERTING:
            self._toast.show("请先停止并保存录音")
            return
        folder = self._latest_folder()
        if not folder or not (folder / 'HANDOFF.md').exists():
            self._toast.show("先完成一次录音，再复制交接说明")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(clipboard_prompt(folder))
        self._toast.show("已复制，可粘贴给 Codex、agy 或其他工具")

    def _on_close(self):
        if self._closing:
            return
        if self.result_panel.busy:
            self.result_panel.cancel()
            self._toast.show('正在取消转录，请稍后关闭')
            return
        if self.controller.state == RecordingState.CONVERTING:
            self._toast.show("正在保存，请稍后关闭")
            return
        if self.controller.is_recording and not messagebox.askyesno("结束录音", "停止并保存当前录音，然后退出？"):
            return
        self._closing = True
        self._save_config()
        def close():
            self.controller.cleanup()
            self._post(self.root.destroy)
        threading.Thread(target=close, daemon=True).start()

    def run(self) -> None:
        """Start application."""
        self.root.mainloop()
