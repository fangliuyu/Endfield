import sys
from pathlib import Path

from src.base import root_log

# 添加核心模块路径到Python路径
core_path = Path(__file__).parent
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))
    root_log.debug(f"添加路径到 sys.path: {core_path}")
