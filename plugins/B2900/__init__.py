
from .main import MainWindow
from src.plugin_manager import register

register(
    name="B2900",
    author="Liuyu.fang",
    version="0.0.1",
    category="Instrument",
    introduction="B2900系列精密直流电源测量控制"
).handler(MainWindow)

