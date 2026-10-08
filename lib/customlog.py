import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from pathlib import Path

Formatter = logging.Formatter(
    '%(asctime)s.%(msecs)03d | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def create_logger(name: str = "", propagate: bool = True, level: int = logging.INFO, log_path: Path = None, time_rotating: bool = True) -> logging.Logger:
    new_logger = logging.getLogger(name=name)
    new_logger.propagate = propagate
    new_logger.setLevel(level=level)
    if log_path:
        new_logger.handlers.clear()
        if time_rotating:
            today = datetime.now().strftime("%y_%m_%d")
            file_handler = TimedRotatingFileHandler(
                filename=log_path / f'{name}_{today}.log',
                when="midnight",
                interval=30,
                backupCount=12,
                encoding="utf-8",
            )
            file_handler.suffix = "%y_%m_%d"
        else:
            file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setFormatter(Formatter)
        new_logger.addHandler(file_handler)
    return new_logger


class CustomFileHandler(logging.FileHandler):
    def __init__(self, filename, mode='a', encoding=None, delay=False, errors=None):
        super().__init__(filename, mode, encoding, delay, errors)
        self.baseFilename = filename  # 保存基础文件路径

    def update_file(self, new_filename):
        # 关闭当前文件流
        self.close()
        # 更新文件路径
        self.baseFilename = new_filename
        # 打开新的文件流
        self.stream = self._open()
