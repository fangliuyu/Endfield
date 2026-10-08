
from pathlib import Path
from typing import Union

from lib.filetools import read_data_from_yaml, save_data_to_yaml


GLOBAL_CONFIG_FILE = "device_list.yaml"


DEFAULT_DEVICE_LISTS = {
    "OSC": {
        "osc_all": ["AgilentTechnologiesMsox", "KeysightTechnologiesDsos", "AgilentTechnologiesDsox", "TektronixMso"],
        "osc_cata": ["KeysightTechnologiesDsos"],
        "osc_tek": ["TektronixMso"],
    },

    "B2900": ["KeysightTechnologiesB29", "AgilentTechnologiesB29"],
    "N6700": ["KeysightTechnologiesN67", "AgilentTechnologiesN67"],
    "2306": ["KeithleyInstruments2306"],

    "DMM": ["KeysightTechnologies344"],

    "FCA3000": ["KeysightTechnologiesFCA3000"],
}


_config_base_dir = None


def register_config_path(base_dir) -> None:
    global _config_base_dir
    _config_base_dir = Path(base_dir)
    file_path = _config_base_dir / GLOBAL_CONFIG_FILE
    if not file_path.exists():
        save_data_to_yaml(DEFAULT_DEVICE_LISTS, file_path)


def get_global_config_path() -> Path:
    base = _config_base_dir if _config_base_dir is not None else Path.cwd()
    return base / GLOBAL_CONFIG_FILE


def load_global_config() -> dict:
    file_path = get_global_config_path()
    if not file_path.exists():
        save_data_to_yaml(DEFAULT_DEVICE_LISTS, file_path)
        return DEFAULT_DEVICE_LISTS
    data = read_data_from_yaml(file_path)
    return {key: data.get(key, default) for key, default in DEFAULT_DEVICE_LISTS.items()}


def save_global_config(data: dict) -> None:
    save_data_to_yaml(data, get_global_config_path())


def get_device_patterns(device_type: str) -> Union[list[str], dict]:
    return load_global_config().get(device_type, [])
