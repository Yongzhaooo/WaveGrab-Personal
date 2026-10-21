"""Dated recording library; annotations live beside each recording."""
from pathlib import Path
import os
import tkinter as tk
from tkinter import ttk
from transcript_store import (SCENES, RAW, default_name, export_result, focused_result,
                              list_recordings, load_details, load_names, load_result, save_details, speaker_ids)


class RecordingsPanel(ttk.Frame):
    def __init__(self, parent, root_folder, open_transcript):
        super().__init__(parent, padding=16)
        self.root_folder, self.open_transcript = root_folder, open_transcript
        self.folder, self.rows, self.people = None, {}, []
        header = ttk.Frame(self)
        header.pack(fill='x', pady=(0, 10))
        ttk.Label(header, text='录音记录', style='Title.TLabel').pack(side='left')
        ttk.Button(header, text='刷新', command=self.refresh).pack(side='right')
        footer = ttk.Frame(self)
        footer.pack(side='bottom', fill='x')
        table = ttk.Frame(self)
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('date', 'duration', 'scene', 'state', 'note'), show='headings', height=8)
        for key, label, width in [('date', '录音日期', 165), ('duration', '时长', 75),
                                   ('scene', '场景', 80), ('state', '状态', 100), ('note', '备注', 300)]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, stretch=key == 'note')
        bar = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side='left', fill='both', expand=True)
        bar.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self.select)
        self.tree.bind('<Double-1>', lambda _: self.open_selected())
        options = ttk.Frame(footer)
        options.pack(fill='x', pady=(12, 6))
        ttk.Label(options, text='文字场景').pack(side='left', padx=(0, 8))
        self.scene = tk.StringVar(value=SCENES['meeting'])
        self.scene_combo = ttk.Combobox(options, textvariable=self.scene, values=list(SCENES.values()), state='readonly', width=26)
        self.scene_combo.pack(side='left')
        self.scene_combo.bind('<<ComboboxSelected>>', lambda _: self.save())
        ttk.Button(options, text='查看 / 转录', command=self.open_selected).pack(side='right')
        ttk.Button(options, text='打开文件夹', command=self.open_folder).pack(side='right', padx=8)
        editor = ttk.Frame(footer)
        editor.pack(fill='x')
        left = ttk.Frame(editor)
        left.pack(side='left', fill='both', expand=True)
        ttk.Label(left, text='简单备注（保存后切换录音也会保留）').pack(anchor='w')
        self.note = tk.Text(left, height=3, wrap='word', font=('Microsoft YaHei UI', 10), relief='solid', borderwidth=1)
        self.note.pack(fill='x', pady=4)
        ttk.Button(left, text='保存备注', command=self.save).pack(anchor='w')
        right = ttk.Frame(editor)
        right.pack(side='right', fill='y', padx=(16, 0))
        ttk.Label(right, text='Desk 正文保留的人（转录后可改选）').pack(anchor='w')
        self.focus = tk.Listbox(right, selectmode='multiple', exportselection=False, height=4, width=31)
        self.focus.pack(fill='x', pady=4)
        buttons = ttk.Frame(right)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='应用选择', command=self.apply_focus).pack(side='left')
        ttk.Button(buttons, text='自动建议', command=self.auto_focus).pack(side='right')
        self.status = tk.StringVar(value='会议保留所有发言；Desk 将未选中的发言另存为待核对稿。')
        ttk.Label(footer, textvariable=self.status, style='Muted.TLabel', wraplength=700).pack(anchor='w', pady=(8, 0))

    def _scene_key(self):
        return next(k for k, v in SCENES.items() if v == self.scene.get())

    @staticmethod
    def _values(row):
        seconds = int(row['seconds'])
        state = {'recording': '录音中', 'incomplete': '未完整保存', 'unreadable': '读取失败'}.get(row['state'],
                 ('无可用语音' if row['audio_warning'] else '已有文字') if row['transcribed'] else '待转录')
        return (row['date'], f'{seconds // 60}:{seconds % 60:02}', 'Desk' if row['scene'] == 'desk' else '会议',
                state, row['note'].replace('\n', ' '))

    def refresh(self):
        if self.folder and not self.save(refresh_people=False):
            return
        selected = str(self.folder) if self.folder else None
        self.rows = {str(r['folder']): r for r in list_recordings(self.root_folder())}
        self.tree.delete(*self.tree.get_children())
        for key, row in self.rows.items():
            self.tree.insert('', 'end', iid=key, values=self._values(row))
        self.folder = None
        if self.rows:
            self.tree.selection_set(selected if selected in self.rows else next(iter(self.rows)))
            self.select()
        else:
            self.note.delete('1.0', 'end')
            self.focus.delete(0, 'end')
            self.people = []
            self.status.set('当前保存目录没有录音')

    def select(self, _=None):
        selected = self.tree.selection()
        if not selected:
            return
        target = Path(selected[0])
        if target == self.folder:
            return
        if self.folder and not self.save(refresh_people=False):
            self.tree.selection_set(str(self.folder))
            return
        try:
            details = load_details(target)
            self.folder = target
            self.scene.set(SCENES[details['scene']])
            self.note.delete('1.0', 'end')
            self.note.insert('1.0', details['note'])
            self.show_people()
        except Exception as exc:
            self.folder = None
            self.note.delete('1.0', 'end')
            self.focus.delete(0, 'end')
            self.people = []
            self.status.set(str(exc))

    def show_people(self):
        self.focus.delete(0, 'end')
        self.people = []
        if not self.folder or not (self.folder / RAW).exists():
            self.status.set('尚未转录；先设置场景和备注，然后点击“查看 / 转录”。')
            return
        data = load_result(self.folder)
        if data.get('audio_warning'):
            self.status.set(data['audio_warning'])
            return
        names = load_names(self.folder, data)
        self.people = speaker_ids(data)
        view, excluded, chosen = focused_result(self.folder, data)
        for index, speaker in enumerate(self.people):
            self.focus.insert('end', names.get(speaker) or default_name(speaker))
            if speaker in chosen:
                self.focus.selection_set(index)
        if self._scene_key() == 'desk':
            automatic = load_details(self.folder)['focus_speakers'] is None
            uncertain = sum(s['speaker'] in ('unknown', 'overlap') for s in view['segments'])
            self.status.set(f'{"自动建议，待核对" if automatic else "已按选择过滤"} · 排除其他声纹 {len(excluded)} 段 · 未知/重叠 {uncertain} 段仍保留；原稿完整。')
        else:
            self.status.set('会议模式保留全部发言，包括未知和重叠片段，不按响度或发言时长过滤。')

    def save(self, refresh_people=True):
        if not self.folder:
            return True
        try:
            details = save_details(self.folder, note=self.note.get('1.0', 'end-1c'), scene=self._scene_key())
            if (self.folder / RAW).exists():
                export_result(self.folder)
            key = str(self.folder)
            if key in self.rows and self.tree.exists(key):
                self.rows[key].update(details)
                self.tree.item(key, values=self._values(self.rows[key]))
            self.status.set('备注与场景已保存')
            if refresh_people:
                self.show_people()
            return True
        except Exception as exc:
            self.status.set('保存失败：' + str(exc))
            return False

    def apply_focus(self):
        if not self.folder or self._scene_key() != 'desk':
            self.status.set('只有 Desk 模式会过滤正文；会议模式始终保留全部。')
            return
        try:
            chosen = [self.people[i] for i in self.focus.curselection()]
            save_details(self.folder, focus_speakers=chosen)
            self.save()
        except Exception as exc:
            self.status.set(str(exc))

    def auto_focus(self):
        if self.folder:
            try:
                save_details(self.folder, focus_speakers=None)
                self.save()
            except Exception as exc:
                self.status.set(str(exc))

    def open_selected(self):
        if self.folder and self.save():
            self.open_transcript(self.folder)

    def open_folder(self):
        if self.folder:
            try:
                os.startfile(self.folder)
            except OSError as exc:
                self.status.set(str(exc))
