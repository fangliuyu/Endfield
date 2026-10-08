
from .main import MainWindow
from src.plugin_manager import register

register(
    name="SSCOM",
    author="Liuyu.fang",
    version="0.0.1",
    category=["FA", "Other"],
    introduction="Soft of Serial COM"
).handler(MainWindow)

