# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for WispGer Flow (Cloud/Groq version — no local model)."""

import os

import customtkinter
ctk_path = os.path.dirname(customtkinter.__file__)

a = Analysis(
    ['wispger_flow.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('fonts', 'fonts'),
        (ctk_path, 'customtkinter'),
    ],
    hiddenimports=[
        'sounddevice', 'pyperclip', 'requests',
        'pynput', 'pynput.keyboard', 'pynput.keyboard._win32',
    ],
    excludes=[
        'numpy', 'torch', 'torchaudio', 'torchvision',
        'faster_whisper', 'ctranslate2',
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
