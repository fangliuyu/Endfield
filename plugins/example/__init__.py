
from .main import MainWindow
from src.plugin_manager import register

register(
    name="Example",
    author="Liuyu.fang",
    version="0.0.1",
    category="Other",
    introduction="这是一个示例插件"
).handler(MainWindow)

