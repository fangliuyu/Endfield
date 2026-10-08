import ast
import logging
import re
import traceback
from typing import Union

ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def process_value(value: str, value_type: str, parameter: str, rule: str, low_limit: Union[str, int, float], up_limit: Union[str, int, float], value_list: dict = None, logger: logging = None):
    state = "PASS"
    result = value
    parameter = parameter.format(value=value, **value_list)

    if rule:
        for line in reversed(value.split('\n')):
            result, state = extract_match(rule, parameter, line)
            if state == "PASS":
                break

        if state == "FAIL":
            result, state = extract_match(rule, parameter, value)
        if logger:
            logger.info(f"match rule {state}: \"{rule}\" match {result}")

    else:
        low_limit = low_limit.format(value=value, **value_list)
        up_limit = up_limit.format(value=value, **value_list)
        limit = low_limit if low_limit else up_limit
        if limit and (value := get_property_value(parameter, limit, value, logger)):
            result = value
            if logger:
                logger.info(f"match parameter {state}: \"{parameter}\" match {value}")

    if state == "FAIL":
        if logger:
            logger.info(f"val process to {state}")
        return result, state

    result = ansi_escape.sub(r'', result, 0)
    val = result
    low = low_limit.format(value=value, **value_list)
    up = up_limit.format(value=value, **value_list)
    try:
        if (low or up) and not val:
            return val, "FAIL"
        if value_type == "小数":
            val = float(result)
            low = float(low)
            up = float(up)
        elif value_type == "整数":
            val = int(result)
            low = int(low)
            up = int(up)
        elif value_type == "十六进制":
            val = int(result, 16)
            low = int(low, 16)
            up = int(up, 16)
        elif value_type != "" and value_type != "文字":
            # 检查result是否有效，避免空字符串导致格式化错误
            if not result or result.strip() == "":
                if logger:
                    logger.warning(f"Cannot format empty result with '{value_type}'")
                val = result
                state = "FAIL"
            else:
                formatted_str = value_type.format(value=result, **value_list)
                try:
                    val = float(eval(formatted_str))
                except (ValueError, SyntaxError):
                    if logger:
                        logger.error(traceback.format_exc())
                    # 如果直接求值失败，尝试清理前导零
                    cleaned_str = re.sub(r'\b0+(\d+)', r'\1', formatted_str)
                    val = float(eval(cleaned_str))
                if logger:
                    logger.info(f"use '{value_type}' change value to {val}")
                result = val
                low = float(low)
                up = float(up)
    except (ValueError, SyntaxError) as e:
        if logger:
            logger.warning(f"Value conversion error: {e}")
        val = result
        low = low_limit.format(value=value, **value_list)
        up = up_limit.format(value=value, **value_list)

    if logger:
        logger.info(f"val translate to {value_type}:\n{'-' * 20}\nup-{up}\tlow-{low}\n{'-' * 20}\n{val}\n{'-' * 20}")
    if (not isinstance(val, str)) or (low or up):
        if isinstance(val, str) and not val:
            state = "FAIL"
        elif low == up and val != up:
            state = "FAIL"
        elif not (low <= val <= up):
            state = "FAIL"

    if logger:
        logger.info(f"val process to {state}")
    return result, state


def extract_match(rule, parameter, value):
    state = "PASS"
    result = re.compile(rule).search(value.strip())
    if not result:
        return value, "FAIL"
    if parameter == "value1=value2":
        value = result.group(1)
        if result.group(1) != result.group(2):
            value = f"{result.group(1)} != {result.group(2)}"
            state = "FAIL"
    else:
        if len(result.groups()) == 1:
            value = result.group(1).strip()
        elif result.group(1) == parameter:
            value = result.group(2).strip()

    return value, state


def get_property_value(property_value: str, expect_value: str, string: str, logger: logging = None):
    expect_value1 = expect_value.replace("\\n", "\n") if expect_value.__contains__("\\n") else expect_value
    if property_value == "none" and expect_value1.__contains__("\n") and expect_value1.__contains__("]"):
        if string.__contains__(expect_value1):
            if logger:
                logger.info(f'Got "{property_value}":"{expect_value}"')
            return expect_value
        else:
            if logger:
                logger.info(f'Get the value of "{property_value}" Failed')
            return None
    else:
        # pattern = re.compile(f"(?<={property}[= :])[\W]*[\w]*[-]?[0]?[x]?[0-9a-zA-Z]+\.?[0-9]*")
        expect_value = expect_value.replace("[", r"\[").replace("]", r"\]")
        pattern = re.compile(f"('?{property_value}'?[= :\n]+)'?({expect_value}|fail)'?")
        if pattern.search(string):
            property_value = pattern.search(string).group(2).strip()
            if logger:
                logger.info(f'Got "{property_value}":"{property_value}"')
            return property_value
        else:
            if logger:
                logger.info(f'Get the value of "{property_value}" Failed')
            return None
