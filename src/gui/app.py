"""Main application window."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import threading

import numpy as np

from paths import get_base_path, get_src_path
import sys
sys.path.insert(0, str(get_src_path()))

from devices import AudioDevice, get_loopback_devices, get_input_devices
from config import AppConfig, load_config, save_config
from .widgets import WaveformCanvas, LevelMeter, OverlayProgress, ToastNotification, COLORS, apply_dark_theme
from .controller import RecordingController, RecordingCallbacks, RecordingState


class AudioRecorderApp:
    """Main GUI application."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("WaveGrab")
        self.root.geometry("620x620")

        # Window icon
        icon_path = get_base_path() / "assets" / "icon_bmp.ico"
        if icon_path.exists():
            self.root.iconbitmap(str(icon_path))
        self.root.minsize(550, 580)
        self.root.resizable(True, True)

        # Load configuration
        self.config = load_config()

        # Apply dark theme
        apply_dark_theme(self.root)

        # Load devices
        self.loopback_devices = get_loopback_devices()
        self.input_devices = get_input_devices()

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
        self.loopback_vol_var = tk.DoubleVar(value=self.config.loopback_volume * 100)
        self.mic_vol_var = tk.DoubleVar(value=self.config.mic_volume * 100)
        self.output_folder_var = tk.StringVar(value=self.config.output_folder or str(Path.cwd()))
        self.filename_var = tk.StringVar(value=self.config.last_filename)
        self.status_var = tk.StringVar(value="Ready")
        self.time_var = tk.StringVar(value="00:00:00")

        # Mini mode state
        self._mini_mode = False
        self._normal_geometry = None

        # Create UI
        self._create_ui()

        # Overlay and toast
        self._overlay = OverlayProgress(self.root, "Converting to MP3...")
        self._toast = ToastNotification(self.root)

        # Restore selections
        self._restore_device_selection()

        # Bind close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Update preview periodically
        self._update_preview()

    def _create_ui(self) -> None:
        """Create user interface."""
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        self._main_frame = main_frame

        # === Devices ===
        devices_frame = ttk.LabelFrame(main_frame, text=" Devices ", padding=10)
        devices_frame.pack(fill=tk.X, pady=(0, 10))
        self._devices_frame = devices_frame

        # Loopback
        ttk.Label(devices_frame, text="Loopback:").grid(row=0, column=0, sticky="w", pady=2)
        loopback_combo = ttk.Combobox(
            devices_frame,
            textvariable=self.loopback_var,
            state="readonly",
            width=50
        )
        # Show name with sample rate
        self._loopback_display_names = ["(None)"] + [
            f"{d.name} [{d.sample_rate}Hz]" for d in self.loopback_devices
        ]
        loopback_combo["values"] = self._loopback_display_names
        loopback_combo.current(0)
        loopback_combo.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        loopback_combo.bind("<<ComboboxSelected>>", self._on_loopback_change)

        # Microphone
        ttk.Label(devices_frame, text="Microphone:").grid(row=1, column=0, sticky="w", pady=2)
        mic_combo = ttk.Combobox(
            devices_frame,
            textvariable=self.mic_var,
            state="readonly",
            width=50
        )
        # Show name with sample rate
        self._mic_display_names = ["(None)"] + [
            f"{d.name} [{d.sample_rate}Hz]" for d in self.input_devices
        ]
        mic_combo["values"] = self._mic_display_names
        mic_combo.current(0)
        mic_combo.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        mic_combo.bind("<<ComboboxSelected>>", self._on_mic_change)

        # Test button
        self.test_btn = ttk.Button(
            devices_frame,
            text="Test",
            command=self._on_test,
            width=8
        )
        self.test_btn.grid(row=0, column=2, rowspan=2, padx=10, pady=2)

        devices_frame.columnconfigure(1, weight=1)

        # === Volume ===
        volume_frame = ttk.LabelFrame(main_frame, text=" Volume ", padding=10)
        volume_frame.pack(fill=tk.X, pady=(0, 10))
        self._volume_frame = volume_frame

        # Loopback volume
        ttk.Label(volume_frame, text="System:").grid(row=0, column=0, sticky="w", pady=2)
        loopback_scale = ttk.Scale(
            volume_frame,
            from_=0, to=100,
            variable=self.loopback_vol_var,
            orient=tk.HORIZONTAL,
            command=self._on_loopback_vol_change
        )
        loopback_scale.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        self.loopback_vol_label = ttk.Label(volume_frame, text="100%", width=5)
        self.loopback_vol_label.grid(row=0, column=2, padx=5)
        self.loopback_meter = LevelMeter(volume_frame, width=80, height=15)
        self.loopback_meter.grid(row=0, column=3, padx=5)

        # Mic volume
        ttk.Label(volume_frame, text="Microphone:").grid(row=1, column=0, sticky="w", pady=2)
        mic_scale = ttk.Scale(
            volume_frame,
            from_=0, to=100,
            variable=self.mic_vol_var,
            orient=tk.HORIZONTAL,
            command=self._on_mic_vol_change
        )
        mic_scale.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        self.mic_vol_label = ttk.Label(volume_frame, text="100%", width=5)
        self.mic_vol_label.grid(row=1, column=2, padx=5)
        self.mic_meter = LevelMeter(volume_frame, width=80, height=15)
        self.mic_meter.grid(row=1, column=3, padx=5)

        volume_frame.columnconfigure(1, weight=1)

        # Update volume labels
        self._on_loopback_vol_change(None)
        self._on_mic_vol_change(None)

        # === Waveform ===
        waveform_frame = ttk.LabelFrame(main_frame, text=" Waveform ", padding=10)
        waveform_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self._waveform_frame = waveform_frame

        self.waveform = WaveformCanvas(waveform_frame, height=100)
        self.waveform.pack(fill=tk.BOTH, expand=True)

        # === Output ===
        output_frame = ttk.LabelFrame(main_frame, text=" Output ", padding=10)
        output_frame.pack(fill=tk.X, pady=(0, 10))
        self._output_frame = output_frame

        # Folder
        ttk.Label(output_frame, text="Folder:").grid(row=0, column=0, sticky="w", pady=2)
        folder_entry = ttk.Entry(output_frame, textvariable=self.output_folder_var)
        folder_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        browse_btn = ttk.Button(output_frame, text="Browse...", command=self._browse_folder)
        browse_btn.grid(row=0, column=2, padx=5, pady=2)

        # Filename
        ttk.Label(output_frame, text="Filename:").grid(row=1, column=0, sticky="w", pady=2)
        filename_entry = ttk.Entry(output_frame, textvariable=self.filename_var)
        filename_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=5, pady=2)
        self.filename_var.trace_add("write", lambda *_: self._update_preview())

        # Preview
        ttk.Label(output_frame, text="Preview:").grid(row=2, column=0, sticky="w", pady=2)
        self.preview_label = ttk.Label(output_frame, text="", foreground=COLORS["fg_dim"])
        self.preview_label.grid(row=2, column=1, columnspan=2, sticky="w", padx=5, pady=2)

        output_frame.columnconfigure(1, weight=1)

        # === Controls ===
        controls_frame = ttk.Frame(main_frame)
        controls_frame.pack(fill=tk.X, pady=(0, 10))
        self._controls_frame = controls_frame

        # Buttons
        btn_frame = ttk.Frame(controls_frame)
        btn_frame.pack()
        self._btn_frame = btn_frame

        self.rec_btn = ttk.Button(
            btn_frame,
            text="  REC",
            command=self._on_rec,
            style="Accent.TButton",
            width=12
        )
        self.rec_btn.pack(side=tk.LEFT, padx=5)

        self.pause_btn = ttk.Button(
            btn_frame,
            text="  PAUSE",
            command=self._on_pause,
            width=12,
            state=tk.DISABLED
        )
        self.pause_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(
            btn_frame,
            text="  STOP",
            command=self._on_stop,
            width=12,
            state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        # Mini mode button (active only during recording)
        self.mini_btn = ttk.Button(
            btn_frame,
            text="Mini",
            command=self._toggle_mini_mode,
            width=6,
            state=tk.DISABLED
        )
        self.mini_btn.pack(side=tk.LEFT, padx=(20, 5))

        # Timer
        self._timer_label = ttk.Label(
            controls_frame,
            textvariable=self.time_var,
            font=("Consolas", 16)
        )
        self._timer_label.pack(pady=8)

        # === Status bar ===
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X)
        self._status_frame = status_frame

        ttk.Label(status_frame, text="Status:").pack(side=tk.LEFT)
        status_label = ttk.Label(
            status_frame,
            textvariable=self.status_var,
            foreground=COLORS["fg_dim"]
        )
        status_label.pack(side=tk.LEFT, padx=5)

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

    def _update_preview(self) -> None:
        """Update filename preview."""
        self.controller.set_filename_prefix(self.filename_var.get())
        preview = self.controller.get_output_filename()
        self.preview_label.configure(text=preview)

    def _browse_folder(self) -> None:
        """Open folder selection dialog."""
        folder = filedialog.askdirectory(
            initialdir=self.output_folder_var.get(),
            title="Select output folder"
        )
        if folder:
            self.output_folder_var.set(folder)
            self.controller.set_output_folder(folder)

    def _on_loopback_change(self, event) -> None:
        """Handle loopback device change."""
        display_name = self.loopback_var.get()
        if display_name == "(None)":
            self.controller.set_loopback_device(None)
        else:
            # Find device by index in list
            idx = self._loopback_display_names.index(display_name) - 1  # -1 for "(None)"
            if 0 <= idx < len(self.loopback_devices):
                self.controller.set_loopback_device(self.loopback_devices[idx])

    def _on_mic_change(self, event) -> None:
        """Handle microphone device change."""
        display_name = self.mic_var.get()
        if display_name == "(None)":
            self.controller.set_mic_device(None)
        else:
            # Find device by index in list
            idx = self._mic_display_names.index(display_name) - 1  # -1 for "(None)"
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
        self.root.minsize(550, 580)
        if self._normal_geometry:
            self.root.geometry(self._normal_geometry)
        else:
            self.root.geometry("620x620")

    def _on_test(self) -> None:
        """Start/stop device test."""
        if self.controller.state == RecordingState.MONITORING:
            self.controller.stop_monitoring()
            self.test_btn.configure(text="Test")
            self.status_var.set("Ready")
        else:
            if self.controller.start_monitoring():
                self.test_btn.configure(text="Stop Test")
                self.status_var.set("Testing - check audio levels")
            else:
                messagebox.showwarning("Warning", "Select at least one device")

    def _on_rec(self) -> None:
        """Start recording."""
        self.controller.set_output_folder(self.output_folder_var.get())
        self.controller.set_filename_prefix(self.filename_var.get())

        if self.controller.start_recording():
            self.test_btn.configure(text="Test", state=tk.DISABLED)
            self.status_var.set("Recording...")

    def _on_pause(self) -> None:
        """Pause or resume recording."""
        if self.controller.state == RecordingState.RECORDING:
            self.controller.pause_recording()
        elif self.controller.state == RecordingState.PAUSED:
            self.controller.resume_recording()

    def _on_stop(self) -> None:
        """Stop recording."""
        # Show immediate visual feedback
        self.root.configure(cursor="wait")
        self._overlay.show()
        self.root.update()

        # Stop in background to not block UI
        def stop_async():
            self.controller.stop_recording()
            self.root.after(0, lambda: self.root.configure(cursor=""))

        threading.Thread(target=stop_async, daemon=True).start()

    def _on_state_change(self, state: RecordingState) -> None:
        """Callback for state change."""
        self.root.after(0, lambda: self._update_ui_state(state))

    def _update_ui_state(self, state: RecordingState) -> None:
        """Update UI based on state."""
        if state == RecordingState.IDLE:
            self._overlay.hide()
            self.rec_btn.configure(state=tk.NORMAL, text="  REC")
            self.pause_btn.configure(state=tk.DISABLED, text="  PAUSE")
            self.stop_btn.configure(state=tk.DISABLED)
            self.test_btn.configure(state=tk.NORMAL, text="Test")
            self.mini_btn.configure(state=tk.DISABLED)
            self.status_var.set("Ready")
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
            self.test_btn.configure(state=tk.NORMAL, text="Stop Test")
            self.mini_btn.configure(state=tk.DISABLED)
            self.status_var.set("Testing - check audio levels")

        elif state == RecordingState.RECORDING:
            self.rec_btn.configure(state=tk.DISABLED)
            self.pause_btn.configure(state=tk.NORMAL, text="  PAUSE")
            self.stop_btn.configure(state=tk.NORMAL)
            self.test_btn.configure(state=tk.DISABLED, text="Test")
            self.mini_btn.configure(state=tk.NORMAL)
            self.status_var.set("Recording...")
            if hasattr(self, '_mini_pause_btn'):
                self._mini_pause_btn.configure(text="||")

        elif state == RecordingState.PAUSED:
            self.rec_btn.configure(state=tk.DISABLED)
            self.pause_btn.configure(state=tk.NORMAL, text="  RESUME")
            self.stop_btn.configure(state=tk.NORMAL)
            self.test_btn.configure(state=tk.DISABLED)
            self.mini_btn.configure(state=tk.NORMAL)
            self.status_var.set("Paused")
            if hasattr(self, '_mini_pause_btn'):
                self._mini_pause_btn.configure(text="▶")

        elif state == RecordingState.CONVERTING:
            self.rec_btn.configure(state=tk.DISABLED)
            self.pause_btn.configure(state=tk.DISABLED)
            self.stop_btn.configure(state=tk.DISABLED)
            self.test_btn.configure(state=tk.DISABLED)
            self.mini_btn.configure(state=tk.DISABLED)
            self.status_var.set("Converting to MP3...")

    def _on_time_update(self, elapsed: float) -> None:
        """Callback for time update."""
        self.root.after(0, lambda: self._update_time(elapsed))

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
        self.root.after(0, update)

    def _on_loopback_level(self, chunk: np.ndarray | None) -> None:
        """Callback for loopback level (during monitoring)."""
        self.root.after(0, lambda: self.loopback_meter.update_from_audio(chunk))

    def _on_mic_level(self, chunk: np.ndarray | None) -> None:
        """Callback for microphone level (during monitoring)."""
        self.root.after(0, lambda: self.mic_meter.update_from_audio(chunk))

    def _on_error(self, message: str) -> None:
        """Callback for errors."""
        self.root.after(0, lambda: messagebox.showerror("Error", message))

    def _on_conversion_complete(self, path: Path) -> None:
        """Callback for conversion complete."""
        self.root.after(0, lambda: self._show_completion(path))

    def _show_completion(self, path: Path) -> None:
        """Show completion message."""
        self.status_var.set(f"Saved: {path.name}")
        self._toast.show(f"Saved: {path.name}", duration=2000)

    def _save_config(self) -> None:
        """Save current configuration."""
        display_loopback = self.loopback_var.get()
        display_mic = self.mic_var.get()

        # Save device name and sample rate
        if display_loopback != "(None)":
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

        if display_mic != "(None)":
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

    def _on_close(self) -> None:
        """Handle application close."""
        if self.controller.is_recording:
            if not messagebox.askyesno(
                "Confirm",
                "Recording in progress. Stop and exit?"
            ):
                return

        self._save_config()
        self.controller.cleanup()
        self.root.destroy()

    def run(self) -> None:
        """Start application."""
        self.root.mainloop()
