
from .main import MainWindow
from src.plugin_manager import register

register(
    name="DMM",
    author="Liuyu.fang; dean.lili",
    version="0.2.0-power-refactor",
    category=["Instrument", "Validation"],
    introduction="台式万用表控制"
).handler(MainWindow)

