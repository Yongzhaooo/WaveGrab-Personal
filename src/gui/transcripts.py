"""Transcript page and the lifecycle of one local inference subprocess."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from handoff import clipboard_prompt
from paths import get_base_path, get_exe_dir, get_src_path, is_frozen
from transcript_store import (RAW, default_name, edit_segment, export_result, install_result,
                              load_edits, load_names, load_result, rename_speaker, speaker_ids, timestamp)


class TranscriptPanel(ttk.Frame):
    def __init__(self, parent, post, active_recording_folder):
        super().__init__(parent, padding=20)
        self.post, self.active_recording_folder = post, active_recording_folder
        self.folder = None
        self.data, self.names, self.edits = None, {}, {}
        self._speaker_lookup = {}
        self.busy = False
        self.process = None
        self.cancelled = threading.Event()
        self.path_var = tk.StringVar(value='选择一次录音，或录完后直接到这里处理')
        self.audio_var, self.status = tk.StringVar(), tk.StringVar(value='音频在本机处理')
        self.count = tk.IntVar(value=0)
        self.speaker_var, self.name_var = tk.StringVar(), tk.StringVar()
        header = ttk.Frame(self)
        header.pack(fill='x', pady=(0, 14))
        ttk.Label(header, text='会议文字', style='Title.TLabel').pack(side='left')
        self.choose_btn = ttk.Button(header, text='打开录音文件夹', command=self.choose_folder)
        self.choose_btn.pack(side='right')
        ttk.Label(self, textvariable=self.path_var, style='Muted.TLabel', wraplength=730).pack(anchor='w')
        options = ttk.Frame(self)
        options.pack(fill='x', pady=12)
        ttk.Label(options, text='音频').pack(side='left', padx=(0, 6))
        self.audio_combo = ttk.Combobox(options, textvariable=self.audio_var, state='readonly', width=18)
        self.audio_combo.pack(side='left', padx=(0, 14))
        ttk.Label(options, text='人数  0 = 自动').pack(side='left', padx=(0, 6))
        self.count_spin = ttk.Spinbox(options, from_=0, to=50, textvariable=self.count, width=4)
        self.count_spin.pack(side='left')
        self.start_btn = ttk.Button(options, text='转录并区分说话人', style='Accent.TButton', command=self.start)
        self.start_btn.pack(side='right')
        progress_row = ttk.Frame(self)
        progress_row.pack(fill='x', pady=(0, 12))
        ttk.Label(progress_row, textvariable=self.status, style='Muted.TLabel').pack(side='left')
        self.cancel_btn = ttk.Button(progress_row, text='取消', command=self.cancel, state='disabled')
        self.cancel_btn.pack(side='right')
        self.progress = ttk.Progressbar(self, mode='indeterminate')
        names = ttk.Frame(self)
        self._names_row = names
        names.pack(fill='x', pady=(0, 12))
        self.speaker_combo = ttk.Combobox(names, textvariable=self.speaker_var, state='readonly', width=15)
        self.speaker_combo.pack(side='left', padx=(0, 8))
        self.speaker_combo.bind('<<ComboboxSelected>>', self.select_speaker)
        self.name_entry = ttk.Entry(names, textvariable=self.name_var, width=20)
        self.name_entry.pack(side='left', padx=(0, 8))
        self.rename_btn = ttk.Button(names, text='整场统一改名', command=self.rename)
        self.rename_btn.pack(side='left')
        ttk.Label(names, text='仅当前会议', style='Muted.TLabel').pack(side='right')
        body = ttk.Frame(self)
        body.pack(fill='both', expand=True)
        table = ttk.Frame(body)
        self.tree = ttk.Treeview(table, columns=('time', 'speaker', 'text'), show='headings', height=9)
        for key, title, width in [('time', '时间', 155), ('speaker', '说话人', 115), ('text', '发言', 400)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, stretch=key == 'text')
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self.show_segment)
        self.tree.bind('<Double-1>', lambda _: self.edit())
        self.detail = tk.Text(body, height=3, wrap='word', relief='flat', bg='#ffffff', fg='#243141',
                              font=('Microsoft YaHei UI', 10), padx=10, pady=8, state='disabled')
        actions = ttk.Frame(body)
        actions.pack(side='bottom', fill='x')
        self.detail.pack(side='bottom', fill='x', pady=(8, 12))
        table.pack(fill='both', expand=True)
        self.edit_btn = ttk.Button(actions, text='校正此段', command=self.edit)
        self.edit_btn.pack(side='left', padx=(0, 8))
        self.refresh_btn = ttk.Button(actions, text='刷新结果', command=self.reload)
        self.refresh_btn.pack(side='left', padx=(0, 8))
        self.export_btn = ttk.Button(actions, text='打开导出', command=self.open_exports)
        self.export_btn.pack(side='right')
        self.handoff_btn = ttk.Button(actions, text='复制清洗交接', command=self.copy_handoff)
        self.handoff_btn.pack(side='right', padx=8)
        self._controls()

    def _controls(self):
        self.choose_btn.configure(state='disabled' if self.busy else 'normal')
        self.audio_combo.configure(state='disabled' if self.busy else 'readonly')
        self.count_spin.configure(state='disabled' if self.busy else 'normal')
        self.start_btn.configure(state='normal' if self.folder and not self.data and not self.busy else 'disabled')
        self.cancel_btn.configure(state='normal' if self.busy else 'disabled')
        for button in (self.rename_btn, self.edit_btn, self.refresh_btn, self.export_btn):
            button.configure(state='normal' if self.data and not self.busy else 'disabled')
        self.handoff_btn.configure(state='normal' if self.folder and not self.busy else 'disabled')

    def choose_folder(self):
        folder = filedialog.askdirectory(title='选择包含录音的文件夹')
        if folder:
            self.set_folder(Path(folder))

    def set_folder(self, folder):
        if self.busy:
            return
        self.folder = Path(folder).resolve()
        self.path_var.set(str(self.folder))
        files = sorted(p.name for p in self.folder.iterdir() if p.is_file() and p.suffix.lower() in ('.flac', '.wav', '.mp3', '.m4a'))
        self.audio_combo['values'] = files
        self.audio_var.set('mixed.flac' if 'mixed.flac' in files else files[0] if files else '')
        self.data, self.names, self.edits = None, {}, {}
        self.tree.delete(*self.tree.get_children())
        self.speaker_combo['values'] = []
        self.speaker_var.set('')
        self.name_var.set('')
        self.status.set('准备就绪 · 点击开始后在本机处理')
        if (self.folder / RAW).exists():
            self.reload()
        self._controls()

    def reload(self):
        if self.busy or not self.folder:
            return
        try:
            self.data, self.names, self.edits = export_result(self.folder)
            self.tree.delete(*self.tree.get_children())
            for segment in self.data['segments']:
                self.tree.insert('', 'end', iid=segment['id'], values=(
                    f'{timestamp(segment["start"])}–{timestamp(segment["end"])}',
                    self.names.get(segment['speaker']) or default_name(segment['speaker']),
                    self.edits.get(segment['id'], segment['text'])))
            self._speaker_lookup = {default_name(s): s for s in speaker_ids(self.data)}
            self.speaker_combo['values'] = list(self._speaker_lookup)
            if self.speaker_var.get() not in self._speaker_lookup:
                self.speaker_var.set(next(iter(self._speaker_lookup), ''))
            self.select_speaker()
            self.status.set(f'{len(speaker_ids(self.data))} 位说话人 · {len(self.data["segments"])} 段发言 · 已导出 Markdown / SRT')
        except Exception as exc:
            self.status.set(f'结果未刷新：{exc}；原始录音和识别结果保留。')
        self._controls()

    def select_speaker(self, _=None):
        speaker = self._speaker_lookup.get(self.speaker_var.get(), '')
        self.name_var.set(self.names.get(speaker) or (default_name(speaker) if speaker else ''))

    def rename(self):
        try:
            rename_speaker(self.folder, self._speaker_lookup.get(self.speaker_var.get(), ''), self.name_var.get())
            self.reload()
        except Exception as exc:
            self.status.set(f'改名未完成：{exc}')

    def show_segment(self, _=None):
        selected = self.tree.selection()
        if not selected or not self.data:
            return
        item = next(s for s in self.data['segments'] if s['id'] == selected[0])
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', self.edits.get(item['id'], item['text']))
        self.detail.configure(state='disabled')

    def edit(self):
        selected = self.tree.selection()
        if not selected or not self.data or self.busy:
            return
        item = next(s for s in self.data['segments'] if s['id'] == selected[0])
        folder = self.folder
        dialog = tk.Toplevel(self)
        dialog.title('校正发言 · 原始转录保留')
        dialog.geometry('620x300')
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        text = tk.Text(dialog, wrap='word', font=('Microsoft YaHei UI', 11), padx=12, pady=12)
        text.pack(fill='both', expand=True, padx=12, pady=12)
        text.insert('1.0', self.edits.get(item['id'], item['text']))
        save_status = tk.StringVar()
        ttk.Label(dialog, textvariable=save_status, wraplength=560).pack(fill='x', padx=12)
        def save():
            try:
                edit_segment(folder, item['id'], text.get('1.0', 'end-1c'))
                dialog.destroy()
                self.reload()
            except Exception as exc:
                save_status.set(f'保存未完成：{exc}')
        ttk.Button(dialog, text='保存校正并更新导出', style='Accent.TButton', command=save).pack(pady=(0, 12))

    def open_exports(self):
        try:
            export_result(self.folder)
            os.startfile(self.folder / 'exports')
        except Exception as exc:
            self.status.set(f'导出失败：{exc}')

    def copy_handoff(self):
        self.clipboard_clear()
        self.clipboard_append(clipboard_prompt(self.folder))
        self.status.set('已复制交接说明，可交给任意支持本地文件的工具')

    def start(self):
        if self.busy or not self.folder:
            return
        active = self.active_recording_folder()
        if active and self.folder.resolve() == Path(active).resolve():
            self.status.set('这一场仍在录制，请先保存；可以处理其他已保存的录音。')
            return
        home = get_exe_dir() if is_frozen() else get_exe_dir() / 'dist'
        python = home / '.runtime' / 'Scripts' / 'python.exe'
        if not python.exists():
            self.status.set('本地转录组件未安装：请先在源码目录运行 Setup-Transcription.cmd。')
            return
        try:
            count = self.count.get()
            if not 0 <= count <= 50:
                raise ValueError('人数填写 0（自动）到 50')
            audio = self.folder / self.audio_var.get()
            if not audio.is_file() or audio.name not in self.audio_combo['values']:
                raise ValueError('请选择有效音频')
            if (self.folder / RAW).exists():
                raise ValueError('已有原始转录，请刷新查看；不会覆盖已有说话人和名称映射。')
            session = self.folder / 'session.json'
            if session.exists() and json.loads(session.read_text(encoding='utf-8')).get('status') == 'recording':
                raise ValueError('这个会话仍标记为录制中，请先停止保存。')
        except Exception as exc:
            self.status.set(f'无法开始：{exc}')
            return
        self.busy = True
        self.cancelled.clear()
        self._controls()
        self.progress.start(15)
        self.progress.pack(fill='x', pady=(0, 8), before=self._names_row)
        self.status.set('正在准备本地模型…')
        script = (get_base_path() if is_frozen() else get_src_path()) / 'transcribe_worker.py'
        threading.Thread(target=self._run, args=(python, script, home, self.folder, audio, count), daemon=True).start()

    def _run(self, python, script, home, folder, audio, count):
        error = None
        try:
            with tempfile.TemporaryDirectory(prefix='wavegrab-transcribe-') as temp:
                result = Path(temp) / 'result.json'
                command = [str(python), '-u', str(script), '--models', str(home / 'models'),
                           '--audio', str(audio), '--output', str(result), '--speakers', str(count)]
                env = os.environ.copy()
                env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
                if self.cancelled.is_set():
                    return
                with (folder / 'transcription.log').open('w', encoding='utf-8') as log:
                    try:
                        if is_frozen() and os.name == 'nt':
                            ctypes.windll.kernel32.SetDllDirectoryW(None)
                        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding='utf-8', errors='replace', env=env,
                            creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
                            if os.name == 'nt' else 0)
                    finally:
                        if is_frozen() and os.name == 'nt':
                            ctypes.windll.kernel32.SetDllDirectoryW(str(get_base_path()))
                    if self.cancelled.is_set():
                        self.process.terminate()
                    last_line = ''
                    for line in self.process.stdout:
                        log.write(line)
                        log.flush()
                        last_line = line.strip()
                        self.post(lambda value=last_line: self.status.set(value[:100]))
                    code = self.process.wait()
                    if not self.cancelled.is_set():
                        if code != 0:
                            raise RuntimeError(last_line or f'处理退出码 {code}，详情见 transcription.log')
                        install_result(folder, json.loads(result.read_text(encoding='utf-8')))
        except Exception as exc:
            error = str(exc)
        finally:
            self.process = None
            self.post(lambda: self._finished(error))

    def _finished(self, error):
        self.busy = False
        self.progress.stop()
        self.progress.pack_forget()
        if self.cancelled.is_set():
            self.status.set('已取消 · 原始录音保留')
        elif error:
            self.status.set(f'处理未完成 · 原始录音保留：{error}')
        else:
            self.reload()
        self._controls()

    def cancel(self):
        self.cancelled.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
        self.status.set('正在取消…')
