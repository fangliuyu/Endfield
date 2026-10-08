
from .main import MainWindow
from src.plugin_manager import register

register(
    name="NIVISA Conctrol",
    author="Liuyu.fang",
    version="0.0.1",
    category="Instrument",
    introduction="用于仪器调试"
).handler(MainWindow)

