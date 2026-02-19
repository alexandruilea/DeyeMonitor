# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for Deye Inverter EMS Pro (Desktop)

import sys
from pathlib import Path

block_cipher = None

# Get the project root
project_root = Path(SPECPATH)

a = Analysis(
    ['main.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Include .env.example as a template
        ('.env.example', '.'),
        # Include app icon for window title bar
        ('icon.ico', '.'),
    ],
    hiddenimports=[
        'pysolarmanv5',
        'pysolarmanv5.pysolarmanv5',
        'tapo',
        'customtkinter',
        'dotenv',
        'src',
        'src.config',
        'src.deye_inverter',
        'src.tapo_manager',
        'src.ems_logic',
        'src.ui_components',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy packages not needed by this app
        'matplotlib', 'numpy', 'scipy', 'pandas',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'pytest', 'lxml', 'psutil', 'setuptools',
        'PIL', 'Pillow', 'IPython', 'jupyter',
        'notebook', 'nbconvert', 'nbformat',
        'sphinx', 'docutils', 'babel',
        'boto3', 'botocore', 'zmq', 'tornado',
        'conda', 'anaconda',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DeyeEMS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app - no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
