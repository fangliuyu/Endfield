# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules


def _collect_plugin_data(plugin_dir):
    """收集插件目录中的非 Python 数据文件，返回 [(src, dst), ...]"""
    datas = []
    for root, dirs, files in os.walk(plugin_dir):
        if '__pycache__' in dirs:
            dirs.remove('__pycache__')
        for f in files:
            if f.endswith('.py') or f.endswith('.pyc') or f.endswith('.pyo'):
                continue
            src = os.path.join(root, f)
            dst = os.path.relpath(root, os.path.dirname(plugin_dir.rstrip('/')))
            datas.append((src, dst))
    return datas

with open(r'./commit.txt', 'r') as f:
    new_version = f.readline().replace("V", "").strip()

hidden_lib = collect_submodules('lib')
hidden_src = collect_submodules('src')
hidden_ui = collect_submodules('ui')
hidden_matplotlib = collect_submodules('matplotlib.backends')
hidden_plugins = ['plugins'] + collect_submodules('plugins')

a = Analysis(
    ['main.py'],
    pathex=['.', '.venv/lib/python3.14/site-packages'],
    binaries=[],
    datas=[('./commit.txt', '.')] + _collect_plugin_data('./plugins')+[('./plugins/SITools/src/analyzer', './plugins/SITools/src/analyzer'), ('./plugins/SITools/src/frames', './plugins/SITools/src/frames'), ('./plugins/example', './plugins/example')],
    hiddenimports=[
        'collections', 'PySide6', 'openpyxl', 'json', 'pathlib',
        'matplotlib', 'pandas', 'numpy', 'abc', 'datetime', 'dataclasses',
        'typing', 'threading', 'traceback', 're', 'importlib', 'ast',
        'shutil', 'subprocess', 'logging', 'os', 'keynote-parser', "python-pptx",
        'matplotlib.backends.backend_svg',  'PIL', 'PIL._imaging',
        'pptx', 'keynote_parser', 'keynote_parser.codec',
        'keynote_parser.file_utils', 'msoffcrypto-tool',
    ] + hidden_lib + hidden_src + hidden_ui + hidden_matplotlib + hidden_plugins,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Endfield',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Endfield',
)
app = BUNDLE(
    coll,
    name='Endfield.app',
    icon='icon.icns',
    bundle_identifier=None,
    info_plist={
        'CFBundleShortVersionString': new_version,
        'NSHighResolutionCapable': 'True',
        'NSHumanReadableCopyright': 'Copyright © 2025 Liuyu.fang All rights reserved.',
    }
)
