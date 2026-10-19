"""Custom GUI widgets."""

import tkinter as tk
from tkinter import ttk
from collections import deque

import numpy as np


COLORS = {
    'bg': '#f5f7fa', 'bg_lighter': '#ffffff', 'fg': '#243141',
    'fg_dim': '#637083', 'accent': '#147d75', 'accent_dark': '#0f635d',
    'waveform': '#3b9b94', 'waveform_dim': '#d8eeea',
    'meter_low': '#369989', 'meter_mid': '#b88420', 'meter_high': '#c44747',
    'border': '#dce3eb', 'disabled': '#9da6b2',
}


class WaveformCanvas(tk.Canvas):
    """Canvas for displaying real-time audio waveform."""

    def __init__(
        self,
        parent: tk.Widget,
        width: int = 500,
        height: int = 100,
        history_size: int = 200,
        **kwargs
    ):
        kwargs.setdefault("bg", COLORS["bg_lighter"])
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(parent, width=width, height=height, **kwargs)

        self._width = width
        self._height = height
        self._history: deque[float] = deque(maxlen=history_size)
        self._center_line = None

        # Draw initial state
        self._draw_background()
        self.bind('<Configure>', self._resize)

    def _resize(self, event):
        self._width, self._height = event.width, event.height
        self._draw_background()
        self._redraw()

    def _draw_background(self) -> None:
        """Draw background and center line."""
        self.delete("all")

        # Center line
        center_y = self._height // 2
        self._center_line = self.create_line(
            0, center_y, self._width, center_y,
            fill=COLORS["border"], width=1, dash=(2, 4)
        )

    def update_waveform(self, audio_chunk: np.ndarray | None) -> None:
        """Update waveform with new audio chunk."""
        if audio_chunk is None or len(audio_chunk) == 0:
            # Add silence if no data
            self._history.append(0.0)
        else:
            # Calculate RMS of chunk
            rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))

            # Convert to dB and normalize
            if rms > 0:
                db = 20 * np.log10(rms / 32768.0)
                # Map from [-60, 0] dB to [0, 1]
                normalized = max(0.0, min(1.0, (db + 60) / 60))
            else:
                normalized = 0.0

            self._history.append(normalized)

        self._redraw()

    def _redraw(self) -> None:
        """Redraw waveform."""
        self.delete("waveform")

        if len(self._history) < 2:
            return

        center_y = self._height // 2
        max_amplitude = (self._height // 2) - 5
        bar_width = self._width / len(self._history)

        # Draw vertical bars for each sample
        for i, amplitude in enumerate(self._history):
            x = i * bar_width
            bar_height = amplitude * max_amplitude

            if bar_height < 1:
                bar_height = 1

            self.create_line(
                x, center_y - bar_height,
                x, center_y + bar_height,
                fill=COLORS["waveform"],
                width=max(1, bar_width - 1),
                tags="waveform"
            )

    def clear(self) -> None:
        """Clear waveform."""
        self._history.clear()
        self._draw_background()


class LevelMeter(tk.Canvas):
    """Horizontal audio level indicator."""

    def __init__(
        self,
        parent: tk.Widget,
        width: int = 100,
        height: int = 15,
        segments: int = 10,
        **kwargs
    ):
        kwargs.setdefault("bg", COLORS["bg_lighter"])
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(parent, width=width, height=height, **kwargs)

        self._width = width
        self._height = height
        self._segments = segments
        self._level = 0.0
        self._peak = 0.0
        self._peak_decay = 0.02

        self._draw()

    def _get_segment_color(self, segment_index: int, total_segments: int) -> str:
        """Return color for segment based on position."""
        position = segment_index / total_segments
        if position < 0.6:
            return COLORS["meter_low"]
        elif position < 0.85:
            return COLORS["meter_mid"]
        else:
            return COLORS["meter_high"]

    def _draw(self) -> None:
        """Draw meter."""
        self.delete("all")

        segment_width = (self._width - (self._segments - 1) * 2) / self._segments
        active_segments = int(self._level * self._segments)
        peak_segment = int(self._peak * self._segments)

        for i in range(self._segments):
            x = i * (segment_width + 2)
            color = COLORS["bg"]

            if i < active_segments:
                color = self._get_segment_color(i, self._segments)
            elif i == peak_segment and self._peak > 0:
                color = self._get_segment_color(i, self._segments)

            self.create_rectangle(
                x, 2, x + segment_width, self._height - 2,
                fill=color, outline=""
            )

    def set_level(self, level: float) -> None:
        """Set level (0.0-1.0)."""
        self._level = max(0.0, min(1.0, level))

        # Update peak
        if self._level > self._peak:
            self._peak = self._level
        else:
            self._peak = max(0, self._peak - self._peak_decay)

        self._draw()

    def update_from_audio(self, audio_chunk: np.ndarray | None) -> None:
        """Update level from audio chunk."""
        if audio_chunk is None or len(audio_chunk) == 0:
            self.set_level(0.0)
            return

        # Calculate RMS
        rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))

        # Convert to dB (logarithmic scale, more realistic for audio)
        # -60 dB = silence, 0 dB = maximum
        if rms > 0:
            db = 20 * np.log10(rms / 32768.0)
            # Map from [-60, 0] dB to [0, 1]
            normalized = max(0.0, min(1.0, (db + 60) / 60))
        else:
            normalized = 0.0

        self.set_level(normalized)

    def clear(self) -> None:
        """Reset meter."""
        self._level = 0.0
        self._peak = 0.0
        self._draw()


class OverlayProgress(tk.Frame):
    """Overlay with progress bar for ongoing operations."""

    def __init__(self, parent: tk.Widget, message: str = "Processing..."):
        super().__init__(parent)

        self._parent = parent
        self.configure(bg=COLORS["bg"])

        # Center frame with border
        center_frame = tk.Frame(self, bg=COLORS["bg_lighter"], padx=40, pady=25)
        center_frame.place(relx=0.5, rely=0.5, anchor="center")

        # Border
        border_frame = tk.Frame(center_frame, bg=COLORS["accent"], padx=2, pady=2)
        border_frame.pack()

        inner_frame = tk.Frame(border_frame, bg=COLORS["bg_lighter"], padx=30, pady=20)
        inner_frame.pack()

        # Message
        self._label = tk.Label(
            inner_frame,
            text=message,
            bg=COLORS["bg_lighter"],
            fg=COLORS["fg"],
            font=("Segoe UI", 11)
        )
        self._label.pack(pady=(0, 15))

        # Progress bar
        self._progress = ttk.Progressbar(
            inner_frame,
            mode="indeterminate",
            length=280
        )
        self._progress.pack()

    def show(self) -> None:
        """Show overlay."""
        self._progress.start(15)
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.lift()
        self.update()

    def hide(self) -> None:
        """Hide overlay."""
        self._progress.stop()
        self.place_forget()

    def set_message(self, message: str) -> None:
        """Update message."""
        self._label.configure(text=message)


class ToastNotification(tk.Frame):
    """Toast notification that appears in center and disappears automatically."""

    def __init__(self, parent: tk.Widget):
        super().__init__(parent, bg=COLORS["accent"], padx=25, pady=15)
        self._parent = parent
        self._after_id = None

        self._label = tk.Label(
            self,
            text="",
            bg=COLORS["accent"],
            fg="#ffffff",
            font=("Segoe UI", 11, "bold")
        )
        self._label.pack()

    def show(self, message: str, duration: int = 3000) -> None:
        """Show notification in center for specified duration (ms)."""
        if self._after_id:
            self._parent.after_cancel(self._after_id)

        self._label.configure(text=message)
        self.place(relx=0.5, rely=0.5, anchor="center")
        self.lift()

        self._after_id = self._parent.after(duration, self.hide)

    def hide(self) -> None:
        """Hide notification."""
        self.place_forget()
        self._after_id = None


def apply_light_theme(root):
    root.configure(bg=COLORS['bg'])
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=COLORS['bg'], foreground=COLORS['fg'], font=('Microsoft YaHei UI', 10))
    style.configure('TFrame', background=COLORS['bg'])
    style.configure('TLabel', background=COLORS['bg'])
    style.configure('Muted.TLabel', foreground=COLORS['fg_dim'])
    style.configure('Brand.TLabel', font=('Segoe UI', 21, 'bold'))
    style.configure('Title.TLabel', font=('Microsoft YaHei UI', 15, 'bold'))
    style.configure('Timer.TLabel', font=('Consolas', 32), foreground=COLORS['fg'])
    style.configure('TButton', padding=(12, 8), background='#ffffff', bordercolor=COLORS['border'])
    style.map('TButton', background=[('active', '#e8eeef')], foreground=[('disabled', COLORS['disabled'])])
    style.configure('Accent.TButton', background=COLORS['accent'], foreground='#ffffff')
    style.map('Accent.TButton', background=[('disabled', '#c6d3d1'), ('active', COLORS['accent_dark'])],
              foreground=[('disabled', '#6d7c7a'), ('!disabled', '#ffffff')])
    style.configure('TEntry', padding=7, fieldbackground='#ffffff', bordercolor=COLORS['border'])
    style.configure('TCombobox', padding=6, fieldbackground='#ffffff', background='#ffffff', bordercolor=COLORS['border'])
    style.map('TCombobox', fieldbackground=[('readonly', '#ffffff')],
              selectbackground=[('readonly', '#ffffff')], selectforeground=[('readonly', COLORS['fg'])])
    style.configure('TNotebook', background=COLORS['bg'], borderwidth=0)
    style.configure('TNotebook.Tab', padding=(18, 10), background='#e9edf2')
    style.map('TNotebook.Tab', background=[('selected', '#ffffff')], foreground=[('selected', COLORS['accent'])])
    style.configure('Treeview', background='#ffffff', fieldbackground='#ffffff', rowheight=32, bordercolor=COLORS['border'])
    style.configure('Treeview.Heading', background='#eaf0f4', padding=8, font=('Microsoft YaHei UI', 10, 'bold'))
    style.map('Treeview', background=[('selected', '#dceeea')], foreground=[('selected', '#174d47')])
    style.configure('Horizontal.TProgressbar', background=COLORS['accent'], troughcolor='#e6ecef')
    style.configure('Horizontal.TScale', background=COLORS['bg'], troughcolor='#dce6e7')
    return style
