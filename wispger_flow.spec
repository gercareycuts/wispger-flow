# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for WispGer Flow — cross-platform (Windows + macOS)."""

import os, sys

import customtkinter
ctk_path = os.path.dirname(customtkinter.__file__)

# Platform-specific hidden imports
hidden = ['sounddevice', 'pyperclip', 'requests', 'pynput', 'pynput.keyboard', 'PIL']
if sys.platform == 'win32':
    hidden += ['pynput.keyboard._win32']
elif sys.platform == 'darwin':
    hidden += ['pynput.keyboard._darwin']

a = Analysis(
    ['wispger_flow.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('fonts', 'fonts'),
        (ctk_path, 'customtkinter'),
    ],
    hiddenimports=hidden,
    excludes=[
        'numpy', 'torch', 'torchaudio', 'torchvision',
        'faster_whisper', 'ctranslate2',
        'matplotlib', 'scipy', 'pandas',
        'IPython', 'jupyter', 'notebook',
        'pytest', 'setuptools', 'pip',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data)

if sys.platform == 'darwin':
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name='WispGer Flow',
        debug=False, strip=False, upx=False,
        console=False,
    )
    app = BUNDLE(
        COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='WispGer Flow'),
        name='WispGer Flow.app',
        bundle_identifier='com.wispger.flow',
    )
else:
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
