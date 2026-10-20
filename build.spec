# -*- mode: python ; coding: utf-8 -*-

import os
from comtypes.client import GetModule

GetModule('UIAutomationCore.dll')

block_cipher = None

# Project base path
BASE_PATH = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    ['src/main_gui.py'],
    pathex=[BASE_PATH, os.path.join(BASE_PATH, 'src')],
    binaries=[],
    datas=[
        ('assets', 'assets'),  # Include assets folder
        ('src/transcribe_worker.py', '.'),
        ('src/speaker_diarization.py', '.'),
        ('licenses', 'licenses'),
    ],
    hiddenimports=[
        'pyaudiowpatch',
        'soundfile',
        'numpy',
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        # src modules
        'paths',
        'devices',
        'recorder',
        'writer',
        'config',
        'comtypes.gen.UIAutomationClient',
        'handoff',
        'gui',
        'gui.app',
        'gui.controller',
        'gui.widgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WaveGrab-Personal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app - no console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon_bmp.ico',  # Exe icon
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name='WaveGrab-Personal')
