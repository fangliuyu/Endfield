import logging
import os
import sys
from pathlib import Path

from lib.customlog import create_logger
from lib.filetools import copy_without_overwrite
from lib.instruments.device_list import register_config_path
from lib.instruments.modules_check import register_module_config_path


if getattr(sys, 'frozen', False):
    root_path = Path(sys.executable).parent / "script"
    if os.name == 'posix':
        root_path = Path(sys.executable).parent.parent / "Resources"
else:
    root_path = Path(__file__).parent.parent
with open(root_path / "commit.txt", 'r', encoding='utf-8') as f:
    version = f.readline().rstrip()

main_path = Path.cwd() / "Endfield_Data"
if getattr(sys, 'frozen', False):
    main_path = Path(sys.executable).parent.resolve()
if os.name == 'posix':
    main_path = Path.home() / "Documents/Endfield"
if not main_path.exists():
    main_path.mkdir()
script_folder = main_path / "script_log"
if not script_folder.exists():
    script_folder.mkdir()
root_log = create_logger(name="Endfield", propagate=False, level=logging.DEBUG, log_path=script_folder)

# data file
plugin_data_path = main_path / "data"
if not plugin_data_path.exists():
    plugin_data_path.mkdir()
register_config_path(plugin_data_path)
builtin_plugins_path = root_path / "plugins"
builtin_plugins_path.mkdir(exist_ok=True)
custom_plugins_path = main_path / "plugins"
custom_plugins_path.mkdir(exist_ok=True)
if not (custom_plugins_path / "example").exists():
    copy_without_overwrite(builtin_plugins_path / "example", custom_plugins_path / "example")
