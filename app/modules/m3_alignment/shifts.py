from datetime import timedelta

# 营业日：夜班 20:00 至次日 08:00 归开工当日；白班 08:00 至 20:00 归自然日。
DAY_START_HOUR = 8
NIGHT_START_HOUR = 20

DAY_SHIFT = "白班"
NIGHT_SHIFT = "夜班"
DAY_ONLY = "按日期"

CROSS_MIDNIGHT = "跨零点归入前一营业日"
SAME_DAY = "营业日当日"
DATE_ONLY = "无时刻按日期判定"


def _parse_clock(value):
    if not isinstance(value, str):
        raise ValueError("时刻需为 HH:MM 字符串")
    try:
        hour, minute = (int(part) for part in value.strip().split(":"))
    except (ValueError, AttributeError) as exc:
        raise ValueError("时刻结构无效") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("时刻超出范围")
    return hour, minute


def shift_for(day, clock):
    """带时刻的读数按 20:00/08:00 切班，返回 (营业日, 班次, 依据)。"""
    if clock is None:
        return day, DAY_ONLY, DATE_ONLY
    hour, _ = _parse_clock(clock)
    if hour < DAY_START_HOUR:
        return day - timedelta(days=1), NIGHT_SHIFT, CROSS_MIDNIGHT
    if hour >= NIGHT_START_HOUR:
        return day, NIGHT_SHIFT, SAME_DAY
    return day, DAY_SHIFT, SAME_DAY


def attribute(day, target_day):
    """无时刻读数的营业日归属：当日，或夜班跨零点顺延的次日。"""
    if day == target_day:
        return day, NIGHT_SHIFT, "无时刻按日期判定：营业日当日"
    if day == target_day + timedelta(days=1):
        return target_day, NIGHT_SHIFT, "无时刻按日期判定：跨零点归入前一营业日"
    return day, DAY_ONLY, DATE_ONLY
