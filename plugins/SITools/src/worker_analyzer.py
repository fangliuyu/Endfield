
import logging
import sys
import importlib
from importlib import util
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QObject, Signal

from .setting import SetupData
from lib.deviceCheck import check_error
from lib.filetools import scan_file_list


class build_analyzer_work(QObject):
    finish_signal = Signal(str, bool, str)  # type, bool, msg

    def __init__(self, parent, config: SetupData, spec_df: pd.DataFrame, data_folder: Path, analyzer_logger: logging.Logger):
        super().__init__(parent)
        self.spec_df = spec_df
        self.logger = analyzer_logger
        self.config = config
        self.data_folder = data_folder

    @check_error
    def run(self):
        self.check_waveform_list()
        analyzer = self.load_analyzer_module()
        new_data = analyzer.analyze_data()
        self.finish_signal.emit("Analyzer", True, "Analyzer SI Data finished.")
        return new_data

    def check_waveform_list(self):
        csv_folder = self.data_folder / "waveform_csv"
        waveform_files = scan_file_list(csv_folder, "csv", with_suffix=True)
        if len(waveform_files) <= 0:
            self.logger.error(f"{csv_folder} doesn't have any waveform file.")
            raise f"{csv_folder} doesn't have any waveform file."

        channel_list = self.config.Oscilloscope.Channel
        for channel, info in channel_list.items():
            if info.EN:
                net: str = info.Net
                csv_path = f"{net}_{channel}_waveform.csv"
                file = self.data_folder / "waveform_csv" / csv_path
                if not file.exists():
                    self.logger.error(f"[I2CAnalyzer::parseCSV] {file.as_posix()} is not existed")
                    raise f"{file.as_posix()} is not existed"

    def load_analyzer_module(self):
        test_item = self.config.Analysis.Name
        if not test_item:
            self.logger.error("Can't get the test item")
            raise "Can't get the test item"
        specification = self.config.Analysis.Configuration.get("specification", "")
        if not specification:
            self.logger.error("Can't get the test specification")
            raise "Can't get the test specification"

        analyzer_module = test_item + "Analyzer"
        analyzer_path = Path(__file__).parent / "analyzer" / analyzer_module

        # 动态导入插件模块
        spec = importlib.util.spec_from_file_location(
            analyzer_module,
            analyzer_path
        )
        self.logger.info(f"set spec to modulename {analyzer_module} from path {analyzer_path}")
        module = importlib.util.module_from_spec(spec)
        self.logger.info(f"load module from spec successfully")

        # 添加插件目录到sys.path以便相对导入
        if (Path(__file__).parent / "analyzer").as_posix() not in sys.path:
            self.logger.info(f"add {analyzer_path} to sys path")
            sys.path.insert(0, (Path(__file__).parent / "analyzer").as_posix())
        sys.modules[analyzer_module] = module
        # 执行模块
        spec.loader.exec_module(module)

        analyzer_t = getattr(module, analyzer_module)
        analyzer = analyzer_t(config=self.config, limits=self.spec_df, data_path=self.data_folder, logger=self.logger)

        return analyzer
