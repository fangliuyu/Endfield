import re

Unit_List = {'m': 1e-3, 'u': 1e-6, 'n': 1e-9, 'p': 1e-12, 'K': 1e3, 'M': 1e6, 'G': 1e9, "%": 1e2}


def get_scale_for_units(unit: str):
    for base_unit, scale in Unit_List.items():
        if base_unit in unit:
            return scale
    return 1.0


def change_value_to_scale(value: float, unit: str):
    for base_unit, scale in Unit_List.items():
        if base_unit in unit:
            return round(value * scale, 10)
    return value


def teardown_str_value_and_unit(value_str: str):
    value = float(re.sub(r'[^-+\d.]+', '', value_str))
    suffix = re.sub(r'[-+\d.]+', '', value_str)
    return value, suffix


def change_str_value_to_scale(value_str: str):
    value, suffix = teardown_str_value_and_unit(value_str)
    return change_value_to_scale(value, suffix)


def set_value_to_scale_str(value: float, decimals: int = 3) -> str:
    suffix_str = ""
    for suffix, scale in Unit_List.items():
        n = abs(value) / scale
        if n < 10:
            value = value / scale
            suffix_str = suffix
            break

    return f"{value:.{decimals}f}{suffix_str}"