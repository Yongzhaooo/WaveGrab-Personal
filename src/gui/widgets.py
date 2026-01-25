"""Custom GUI widgets."""

import tkinter as tk
from tkinter import ttk
from collections import deque

import numpy as np


# Dark theme colors
COLORS = {
    "bg": "#1e1e1e",
    "bg_lighter": "#2d2d2d",
    "fg": "#ffffff",
    "fg_dim": "#888888",
    "accent": "#22c55e",        # Green for REC and toast
    "accent_dark": "#16a34a",   # Dark green
    "waveform": "#00ff88",
    "waveform_dim": "#004422",
    "meter_low": "#00ff88",
    "meter_mid": "#ffcc00",
    "meter_high": "#ff4444",
    "border": "#3d3d3d",
    "disabled": "#555555",
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
        self.configure(bg="#000000")

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
            fg=COLORS["fg"],
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


def apply_dark_theme(root: tk.Tk) -> ttk.Style | None:
    """Apply dark theme to a tk window."""
    root.configure(bg=COLORS["bg"])

    style = None
    try:
        style = ttk.Style()

        # Base theme
        style.theme_use("clam")

        # General background
        style.configure(".", background=COLORS["bg"], foreground=COLORS["fg"])

        # Frame
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("TLabelframe", background=COLORS["bg"])
        style.configure("TLabelframe.Label", background=COLORS["bg"], foreground=COLORS["fg"])

        # Label
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["fg"])

        # Button
        style.configure(
            "TButton",
            background=COLORS["bg_lighter"],
            foreground=COLORS["fg"],
            borderwidth=1,
            focuscolor=COLORS["accent"]
        )
        style.map(
            "TButton",
            background=[
                ("disabled", COLORS["bg"]),
                ("active", COLORS["accent_dark"]),
                ("pressed", COLORS["accent"])
            ],
            foreground=[
                ("disabled", COLORS["disabled"]),
                ("active", COLORS["fg"])
            ]
        )

        # Accent Button
        style.configure(
            "Accent.TButton",
            background=COLORS["accent"],
            foreground=COLORS["fg"]
        )
        style.map(
            "Accent.TButton",
            background=[("active", COLORS["accent_dark"]), ("pressed", COLORS["accent_dark"])]
        )

        # Combobox
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["bg_lighter"],
            background=COLORS["bg_lighter"],
            foreground=COLORS["fg"],
            arrowcolor=COLORS["fg"]
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", COLORS["bg_lighter"])],
            selectbackground=[("readonly", COLORS["accent"])],
            selectforeground=[("readonly", COLORS["fg"])]
        )

        # Entry
        style.configure(
            "TEntry",
            fieldbackground=COLORS["bg_lighter"],
            foreground=COLORS["fg"],
            insertcolor=COLORS["fg"]
        )

        # Scale (slider)
        style.configure(
            "TScale",
            background=COLORS["bg"],
            troughcolor=COLORS["bg_lighter"],
            sliderthickness=15
        )
        style.configure(
            "Horizontal.TScale",
            background=COLORS["bg"],
            troughcolor=COLORS["bg_lighter"]
        )

        # Scrollbar
        style.configure(
            "TScrollbar",
            background=COLORS["bg_lighter"],
            troughcolor=COLORS["bg"],
            arrowcolor=COLORS["fg"]
        )

    except Exception:
        pass  # Fallback if ttk doesn't work

    return style
