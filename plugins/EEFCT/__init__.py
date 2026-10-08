
from .main import MainWindow
from src.plugin_manager import register

register(
    name="EEFCT",
    author="Liuyu.fang",
    version="6.0.1.20251113",
    category="FA",
    introduction="EE FunctionCheckTest Station"
).handler(MainWindow)

