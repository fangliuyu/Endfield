
from .main import MainWindow
from src.plugin_manager import register

register(
    name="FCA3000",
    author="Liuyu.fang",
    version="0.0.1",
    category="Instrument",
    introduction="FCA3000频率采集仪控制"
).handler(MainWindow)

