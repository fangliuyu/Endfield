from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict

from lib.filetools import read_data_from_yaml, save_data_to_yaml


@dataclass
class SerialConfig:
    Enable: bool
    Name: str
    Baud: int


@dataclass
class SettingConfig:
    CommandFile: str
    ShowCmd: bool
    FailStop: bool
    Serial: Dict[int, SerialConfig]


def read_setting_file(file: Path) -> SettingConfig:
    data = read_data_from_yaml(file)
    setting_info = SettingConfig(**data)
    return setting_info


def save_setting_file(setting_info: SettingConfig, file: Path):
    data = asdict(setting_info)
    save_data_to_yaml(data, file)
