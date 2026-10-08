from pathlib import Path

from lib.filetools import save_data_to_yaml, read_data_from_yaml


MODULE_FILE = "modules_list.yaml"


DEFAULT_N6700_PATTERNS = {
    "DC Power": ["N673xB", "N674xB", "N677xA", "N675xA", "N676xA"],
    "Source Measure Unit": ["N678xA"],
    "Electronic Load": ["N679xA"],
    "Precision DC Power": ["N6761A", "N6762A"],
}

DEFAULT_N6700_MODULES = {
    "N6731B": {
        "Description": "50W 5V DC Power Module",
        "PowerRating": 50,
        "VoltageRating": 5,
        "CurrentRating": 10,
    },
    "N6732B": {
        "Description": "50W 8V DC Power Module",
        "PowerRating": 50,
        "VoltageRating": 8,
        "CurrentRating": 6.25,
    },
    "N6733B": {
        "Description": "50W 20V DC Power Module",
        "PowerRating": 50,
        "VoltageRating": 20,
        "CurrentRating": 2.5,
        'VoltageRange': [20.4],
        'CurrentRange': [2.55]
    },
    "N6734B": {
        "Description": "50W 35V DC Power Module",
        "PowerRating": 50,
        "VoltageRating": 35,
        "CurrentRating": 1.5,
    },
    "N6735B": {
        "Description": "50W 60V DC Power Module",
        "PowerRating": 50,
        "VoltageRating": 60,
        "CurrentRating": 0.8,
    },
    "N6736B": {
        "Description": "50W 100V DC Power Module",
        "PowerRating": 50,
        "VoltageRating": 100,
        "CurrentRating": 0.5,
    },
    "N6741B": {
        "Description": "100W 5V DC Power Module",
        "PowerRating": 100,
        "VoltageRating": 5,
        "CurrentRating": 20,
    },
    "N6742B": {
        "Description": "100W 8V DC Power Module",
        "PowerRating": 100,
        "VoltageRating": 8,
        "CurrentRating": 12.5,
    },
    "N6743B": {
        "Description": "100W 20V DC Power Module",
        "PowerRating": 100,
        "VoltageRating": 20,
        "CurrentRating": 5,
    },
    "N6744B": {
        "Description": "100W 35V DC Power Module",
        "PowerRating": 100,
        "VoltageRating": 35,
        "CurrentRating": 3,
    },
    "N6745B": {
        "Description": "100W 60V DC Power Module",
        "PowerRating": 100,
        "VoltageRating": 60,
        "CurrentRating": 1.6,
        'VoltageRange': [61.2],
        'CurrentRange': [1.7],
    },
    "N6746B": {
        "Description": "100W 100V DC Power Module",
        "PowerRating": 100,
        "VoltageRating": 100,
        "CurrentRating": 1,
    },
    "N6773A": {
        "Description": "300W 20V DC Power Module",
        "PowerRating": 300,
        "VoltageRating": 20,
        "CurrentRating": 15,
    },
    "N6774A": {
        "Description": "300W 35V DC Power Module",
        "PowerRating": 300,
        "VoltageRating": 35,
        "CurrentRating": 8.5,
    },
    "N6775A": {
        "Description": "300W 60V DC Power Module",
        "PowerRating": 300,
        "VoltageRating": 60,
        "CurrentRating": 5,
    },
    "N6776A": {
        "Description": "300W 100V DC Power Module",
        "PowerRating": 300,
        "VoltageRating": 100,
        "CurrentRating": 3,
    },
    "N6777A": {
        "Description": "300W 100V DC Power Module",
        "PowerRating": 300,
        "VoltageRating": 150,
        "CurrentRating": 2,
    },
    "N6751A": {
        "Description": "50W High-Performance AutoRanging DC Power Module",
        "PowerRating": 50,
        "VoltageRating": 50,
        "CurrentRating": 5,
    },
    "N6752A": {
        "Description": "100W High-Performance AutoRanging DC Power Module",
        "PowerRating": 100,
        "VoltageRating": 50,
        "CurrentRating": 10,
    },
    "N6753A": {
        "Description": "300W High-Performance AutoRanging DC Power Module",
        "PowerRating": 300,
        "VoltageRating": 20,
        "CurrentRating": 50,
    },
    "N6754A": {
        "Description": "300W High-Performance AutoRanging DC Power Module",
        "PowerRating": 300,
        "VoltageRating": 60,
        "CurrentRating": 20,
    },
    "N6755A": {
        "Description": "500W High-Performance AutoRanging DC Power Module",
        "PowerRating": 500,
        "VoltageRating": 20,
        "CurrentRating": 50,
    },
    "N6756A": {
        "Description": "500W High-Performance AutoRanging DC Power Module",
        "PowerRating": 500,
        "VoltageRating": 60,
        "CurrentRating": 17,
    },
    "N6761A": {
        "Description": "50W Precision DC Power Module",
        "PowerRating": 50,
        "VoltageRating": 50,
        "CurrentRating": 1.5,
        "Operating": ["Voltage", "Current"]
    },
    "N6762A": {
        "Description": "100W Precision DC Power Module",
        "PowerRating": 100,
        "VoltageRating": 50,
        "CurrentRating": 3,
        "Operating": ["Voltage", "Current"]
    },
    "N6763A": {
        "Description": "300W Precision DC Power Module",
        "PowerRating": 300,
        "VoltageRating": 20,
        "CurrentRating": 50,
    },
    "N6764A": {
        "Description": "300W Precision DC Power Module",
        "PowerRating": 300,
        "VoltageRating": 60,
        "CurrentRating": 20,
    },
    "N6765A": {
        "Description": "500W Precision DC Power Module",
        "PowerRating": 500,
        "VoltageRating": 20,
        "CurrentRating": 50,
    },
    "N6766A": {
        "Description": "500W Precision DC Power Module",
        "PowerRating": 500,
        "VoltageRating": 60,
        "CurrentRating": 17,
    },
    "N6781A": {
        "Description": "2-Quadrant Source/Measure Unit for Battery Drain Analysis (20 W)",
        "PowerRating": 20,
        "VoltageRating": 20,
        "CurrentRating": 3,
        "VoltageRange": [0.612, 6.12, 20.4],
        "CurrentRange": [0.306, 1.02, 3.06],
        'Emulation': ["PS2Q", "PS1Q", "BATTery", "CHARger", "CCLoad", "CVLoad", "VMETer", "AMETer"],
        "Operating": ["Voltage", "Current"]
    },
    "N6782A": {
        "Description": "2-Quadrant Source/Measure Unit for Functional Test (20 W)",
        "PowerRating": 20,
        "VoltageRating": 20,
        "CurrentRating": 3,
        "VoltageRange": [0.612, 6.12, 20.4],
        "CurrentRange": [0.306, 1.02, 3.06],
        'Emulation': ["PS2Q", "PS1Q", "CCLoad", "CVLoad", "VMETer", "AMETer"],
        "Operating": ["Voltage", "Current"]
    },
    "N6784A": {
        "Description": "4-Quadrant General Purpose Source/Measure Unit (20 W)",
        "PowerRating": 20,
        "VoltageRating": 20,
        "CurrentRating": 3,
        "VoltageRange": [0.612, 6.12, 20.4],
        "CurrentRange": [1.02, 3.06],
        'Emulation': ["PS4Q", "PS2Q", "PS1Q", "CCLoad", "CVLoad", "VMETer", "AMETer"],
        "Operating": ["Voltage", "Current"]
    },
    "N6785A": {
        "Description": "2-Quadrant Source/Measure Unit for Battery Drain Analysis (80 W)",
        "PowerRating": 80,
        "VoltageRating": 20,
        "CurrentRating": 8,
        "VoltageRange": [6.12, 10.2, 15.3, 20.4],
        "CurrentRange": [4.08, 5.1, 6.834, 8.16],
        'Emulation': ["PS2Q", "PS1Q", "BATTery", "CHARger", "CCLoad", "CVLoad", "VMETer", "AMETer"],
        "Operating": ["Voltage", "Current"]
    },
    "N6786A": {
        "Description": "2-Quadrant Source/Measure Unit for Functional Test (80 W)",
        "PowerRating": 80,
        "VoltageRating": 20,
        "CurrentRating": 8,
        "VoltageRange": [6.12, 10.2, 15.3, 20.4],
        "CurrentRange": [4.08, 5.1, 6.834, 8.16],
        'Emulation': ["PS2Q", "PS1Q", "CCLoad", "CVLoad", "VMETer", "AMETer"],
        "Operating": ["Voltage", "Current"]
    },
    "N6783A": {
        "Description": "24W Source/Measure Unit (2Q SMU)",
        "PowerRating": 24,
        "VoltageRating": 8,
        "CurrentRating": 3,
    },
    "N6783A-BAT": {
        "Description": "18W Battery Application-Specific DC Power",
        "PowerRating": 18,
        "VoltageRating": 6,
        "CurrentRating": 3,
    },
    "N6783A-MFG": {
        "Description": "24W MFG Application-Specific DC Power",
        "PowerRating": 24,
        "VoltageRating": 8,
        "CurrentRating": 3,
    },
    "N6791A": {
        "Description": "100W Electronic Load Module",
        "PowerRating": 100,
        "VoltageRating": 60,
        "CurrentRating": 20,
        "PowerRange": [100*1.02, 10*1.02],
        "ResistanceRange": [8000, 100, 3],
        "Operating": ["Voltage", "Current", "Resistance", "Power"]
    },
    "N6792A": {
        "Description": "200W Electronic Load Module",
        "PowerRating": 200,
        "VoltageRating": 60,
        "CurrentRating": 40,
        "PowerRange": [200*1.02, 20*1.02],
        "ResistanceRange": [8000, 100, 3],
        "Operating": ["Voltage", "Current", "Resistance", "Power"]
    },
}

def _module_defaults() -> dict:
    return {
        "n6700_patterns": DEFAULT_N6700_PATTERNS,
        "n6700_modules": DEFAULT_N6700_MODULES,
    }


_module_config_base_dir = None


def register_module_config_path(base_dir) -> None:
    global _module_config_base_dir
    _module_config_base_dir = Path(base_dir)


def get_module_config_path() -> Path:
    base = _module_config_base_dir if _module_config_base_dir is not None else Path.cwd()
    return base / MODULE_FILE


def load_multi() -> dict:
    file_path = get_module_config_path()
    if not file_path.exists():
        default = _module_defaults()
        save_data_to_yaml(default, file_path)
        return default
    data = read_data_from_yaml(file_path)
    return {key: data.get(key, default) for key, default in _module_defaults().items()}


def save_multi(data: dict) -> None:
    save_data_to_yaml(data, get_module_config_path())


def get_module_patterns(module_type: str) -> dict:
    return load_multi().get(module_type, {})
