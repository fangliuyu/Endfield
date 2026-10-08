# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
    StringStruct, VarFileInfo, VarStruct
)

with open(r'./commit.txt', 'r', encoding="utf-8") as f:
    new_version = f.readline().replace("V", "").strip()
version_bit = list(map(int, new_version.split('.')))
version_bit[-1] = version_bit[-1] - int(version_bit[-1]/100000)*100000
version = tuple(version_bit)

# 版本信息
version_info = VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=version,   # 文件版本号 (四段式数字，必须与下方字符串版本对应)
    prodvers=version,      # 产品版本号
    mask=0x3f,                  # 有效性掩码 (通常保持默认)
    flags=0x0,                  # 文件特性标志 (0x0=无特殊标志)
    OS=0x40004,                 # 目标操作系统 (0x40004=Win32)
    fileType=0x1,               # 文件类型 (0x1=应用程序)
    subtype=0x0,                # 文件子类型 (0x0=无)
    date=(0, 0)                 # 编译时间 (0,0=自动生成)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', '歌尔股份有限公司'),
        StringStruct('FileDescription', 'Liuyu为EE设计的工具合集'),
        StringStruct('FileVersion', new_version),
        StringStruct('InternalName', 'Endfield.exe'),
        StringStruct('LegalCopyright', 'Copyright © 2025 Liuyu.fang All rights reserved.'),
        StringStruct('OriginalFilename', 'Endfield.exe'),
        StringStruct('ProductName', 'Endfield'),
        StringStruct('ProductVersion', new_version),
        StringStruct('SquirrelAwareVersion', '1')])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)

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



hidden_lib = collect_submodules('lib')
hidden_src = collect_submodules('src')
hidden_ui = collect_submodules('ui')
hidden_matplotlib = collect_submodules('matplotlib.backends')
hidden_plugins = ['plugins'] + collect_submodules('plugins')


a = Analysis(
    ['main.py'],
    pathex=['.', 'E:\2-python\venv\Endfield\Lib\site-packages'],
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
    contents_directory='script',
    version=version_info,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Endfield',
)
