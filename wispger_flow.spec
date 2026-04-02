# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for WispGer Flow (faster-whisper, no PyTorch)."""

import os

import customtkinter
import faster_whisper
ctk_path = os.path.dirname(customtkinter.__file__)
fw_assets = os.path.join(os.path.dirname(faster_whisper.__file__), 'assets')

a = Analysis(
    ['wispger_flow.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('models/base-ct2', 'models/base-ct2'),
        (ctk_path, 'customtkinter'),
        (fw_assets, 'faster_whisper/assets'),
    ],
    hiddenimports=[
        'faster_whisper', 'ctranslate2',
        'sounddevice', 'pyperclip',
        'pynput', 'pynput.keyboard', 'pynput.keyboard._win32',
    ],
    excludes=[
        'torch', 'torchaudio', 'torchvision',
        'matplotlib', 'PIL', 'scipy', 'pandas',
        'IPython', 'jupyter', 'notebook',
        'pytest', 'setuptools', 'pip',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='WispGer Flow',
    debug=False, strip=False, upx=True,
    console=True,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=True,
    name='WispGer Flow',
)
