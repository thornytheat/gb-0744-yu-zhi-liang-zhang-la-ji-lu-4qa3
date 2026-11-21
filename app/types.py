class DataFault(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def evidence(row, code):
    item = {
        "梁号": row.get("beam", ""),
        "钢束": row.get("strand", ""),
        "端位": row.get("end", ""),
        "源行": row["line"],
        "原因码": code,
    }
    if row.get("day") is not None:
        item["记录日"] = row["day"].isoformat()
    if row.get("business_day") is not None:
        item["营业日"] = row["business_day"].isoformat()
    if row.get("shift"):
        item["班次依据"] = f"{row['shift']}·{row.get('shift_basis', '')}"
    return item
