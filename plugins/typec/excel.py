import re

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill, Alignment
from openpyxl.utils import get_column_letter

from pathlib import Path
from typing import Union
from collections import OrderedDict


def read_xlsx_file(xlsx_file: Union[str, Path]) -> OrderedDict:
    wb = None
    treeview_rows = OrderedDict()
    try:
        # 加载Excel工作簿
        wb = load_workbook(filename=xlsx_file)
        ws = wb.active  # 获取第一个工作表

        # 获取表头
        li = [cell.value for cell in ws[3]]

        # 创建列名到索引的映射
        headers = {col_name: idx for idx, col_name in enumerate(li) if col_name}

        index = 0

        # 从第二行开始读取数据
        for row_idx, row in enumerate(ws.iter_rows(min_row=4), 1):
            # 检查Enable列是否为1
            enable_col = headers.get('EN', 0)
            if not row[enable_col].value:
                continue

            index += 1
            row_data = {}

            for col_name, col_idx in headers.items():
                if col_name != "EN":
                    cell_value = row[col_idx].value
                    row_data[col_name] = str(cell_value) if str(cell_value).isdigit() or not (cell_value is None) else ""

            row_data['Sequence'] = index
            treeview_rows[row_idx] = row_data

    except Exception as e:
        raise ValueError(f"读取Excel文件时出错: {str(e)}")
    finally:
        wb.close()  # 确保关闭工作簿

    return treeview_rows


def save_data_to_xlsx(xlsx_file: Union[str, Path], row_data: list, rule_index: int, rule_value: str, command_index: int):
    # 定义红色填充
    red_fill = PatternFill(start_color="FFFF0000", end_color="FFFF0000", fill_type="solid")

    wb = Workbook()
    ws = wb.active

    try:
        # 清理数据中的非法字符
        cleaned_data = []
        for data_row in row_data:
            cleaned_row = []
            for item in data_row:
                if isinstance(item, str):
                    # 移除 ANSI 转义序列
                    cleaned_item = clean_string_for_excel(item)
                else:
                    cleaned_item = item
                cleaned_row.append(cleaned_item)
            cleaned_data.append(cleaned_row)

        for row, data in enumerate(cleaned_data, 1):  # 从第1行开始
            ws.append(data)

            # 检查规则条件并设置红色填充
            if rule_index < len(data) and data[rule_index] == rule_value:
                row_cells = ws[row]  # 当前行的所有单元格
                for cell in row_cells:
                    cell.fill = red_fill

        # 设置命令列的文本换行
        if command_index < len(ws[1]):  # 确保列索引有效
            col_letter = get_column_letter(command_index + 1)  # 转换为1-based索引
            for cell in ws[col_letter]:
                cell.alignment = Alignment(wrap_text=True)

        # 自动调整列宽
        for col in ws.columns:
            max_width = 0
            column_letter = None
            for cell in col:
                if cell.value is not None:
                    # 计算单元格内容的宽度
                    cell_width = len(str(cell.value))
                    max_width = max(max_width, cell_width)
                if column_letter is None:
                    column_letter = get_column_letter(cell.column)

            if column_letter and max_width > 0:
                # 设置列宽，留出一些边距
                ws.column_dimensions[column_letter].width = min(max_width + 2, 50)  # 限制最大宽度

        # 保存文件
        wb.save(xlsx_file)

    except Exception as e:
        raise e
    finally:
        wb.close()


def clean_string_for_excel(text):
    """清理字符串，移除 Excel 不允许的字符"""
    if not isinstance(text, str):
        return text

    # 移除 ANSI 转义序列
    text = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', text)

    # 移除控制字符（保留制表符、换行符、回车符）
    cleaned_chars = []
    for char in text:
        if ord(char) >= 32 or ord(char) in [9, 10, 13]:  # 可打印字符 + 制表符、换行符、回车符
            cleaned_chars.append(char)

    return ''.join(cleaned_chars)
