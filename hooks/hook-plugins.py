# PyInstaller hook for plugins module
# Ensures that all plugin submodules are properly included
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Collect all plugin submodules
hiddenimports = ['plugins'] + collect_submodules('plugins')

# Collect plugin data files (non-Python files)
datas = collect_data_files('plugins', include_py_files=False)
