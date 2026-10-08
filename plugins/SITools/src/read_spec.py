
from pathlib import Path
from typing import Optional
import pandas as pd


def read_spec_excel(path: Path, base_voltage: str) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    df = pd.read_excel(path)
    df.dropna(how="all")
    df.fillna(value="-", inplace=True)
    limit_df = pd.DataFrame(columns=df.columns)
    info = {}
    names = df.columns.tolist()
    for i in range(len(names)):
        info[names[i]] = i

    for index, row in df.iterrows():
        lower_func = str(row.iloc[info.get("Lower Limit", 2)])
        lower_limit = "-"
        if lower_func != "-":
            lower_func = lower_func.lower().replace("vin", base_voltage)
            lower_limit = eval(lower_func)
            if lower_limit % 1 != 0:
                lower_limit = float("{:.3f}".format(lower_limit))

        lower_warn_func = str(row.iloc[info.get("Lower Warning", 3)])
        lower_warn_limit = "-"
        if lower_warn_func != "-":
            lower_warn_func = lower_warn_func.lower().replace("vin", base_voltage)
            lower_warn_limit = eval(lower_warn_func)
            if lower_warn_limit % 1 != 0:
                lower_warn_limit = float("{:.3f}".format(lower_warn_limit))

        upper_warn_func = str(row.iloc[info.get("Upper Warning", 4)])
        upper_warn_limit = "-"
        if upper_warn_func != "-":
            upper_warn_func = upper_warn_func.lower().replace("vin", base_voltage)
            upper_warn_limit = eval(upper_warn_func)
            if upper_warn_limit % 1 != 0:
                upper_warn_limit = float("{:.3f}".format(upper_warn_limit))

        upper_func = str(row.iloc[info.get("Upper Limit", 5)])
        upper_limit = "-"
        if upper_func != "-":
            upper_func = upper_func.lower().replace("vin", base_voltage)
            upper_limit = eval(upper_func)
            if upper_limit % 1 != 0:
                upper_limit = float("{:.3f}".format(upper_limit))

        row_data = {
            "Net.": row.iloc[info.get("Net.", 0)],
            "Measurement": row.iloc[info.get("Measurement", 1)],
            "Lower Limit": lower_limit,
            "Lower Warning": lower_warn_limit,
            "Upper Warning": upper_warn_limit,
            "Upper Limit": upper_limit,
            "Unit": row.iloc[info.get("Unit", 6)],
        }
        # new_row = pd.DataFrame(row_data, columns=df.columns)
        # limit_df = pd.concat([limit_df, new_row], axis="columns")
        # limit_df = limit_df._append(row_data, ignore_index=True)
        limit_df.loc[index] = row_data

    return limit_df

