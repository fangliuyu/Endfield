import os
import shutil
import traceback
from pathlib import Path

import yaml


def copy_without_overwrite(src_path: Path, dst_path: Path):
    if not dst_path.exists():
        dst_path.mkdir(parents=True)
    try:
        for item in src_path.iterdir():
            src_item = item
            dst_item = dst_path / item.name
            if src_item.is_dir():
                if not dst_item.exists():
                    dst_item.mkdir()
                copy_without_overwrite(src_item, dst_item)
            else:
                if not dst_item.exists():
                    shutil.copy2(src_item, dst_item)
    except Exception:
        raise Exception(traceback.format_exc())


def scan_file_list(path: Path, suffix: str, with_suffix: bool = False, scan_children: bool = False) -> list:
    if not path.exists():
        raise Exception("the path not exists!")

    if scan_children:
        file_list = list(path.glob(f'**/*.{suffix}'))
        files = [file.relative_to(path) for file in file_list]
        if not with_suffix:
            files = [file.with_suffix('') for file in files]
    else:
        file_list = list(path.glob(f'*.{suffix}'))
        files = [file.name if with_suffix else file.stem for file in file_list]

    # 按路径深度优先，再按名称排序
    files = sorted(files, key=lambda x: (
        -len(str(x).split(os.sep)) if scan_children else 0,  # 路径深度（目录层级数）
        x.name if hasattr(x, 'name') else str(x)  # 文件名
    ))

    return files


def read_data_from_yaml(file: Path, encoding: str = 'utf8') -> dict:
    if not file.exists():
        raise Exception(f"the {file.stem} not exists!")
    try:
        with open(file, "r", encoding=encoding) as f:
            data = yaml.load(f, Loader=yaml.FullLoader)
            return data
    except Exception:
        raise Exception(traceback.format_exc())


def save_data_to_yaml(data: dict, file: Path, encoding: str = 'utf8'):
    try:
        with open(file, "w") as f:
            yaml.dump(data, f, encoding=encoding, allow_unicode=True, sort_keys=False)
    except Exception:
        raise Exception(traceback.format_exc())
