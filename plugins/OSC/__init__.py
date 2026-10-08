
from .main import MainWindow
from src.plugin_manager import register

register(
    name="OSC",
    author="Liuyu.fang",
    version="0.0.1",
    category="Instrument",
    introduction="示波器控制"
).handler(MainWindow)
