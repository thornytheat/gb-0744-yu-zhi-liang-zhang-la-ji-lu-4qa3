from datetime import timedelta
from decimal import Decimal

from app.modules.m3_alignment.shifts import attribute, shift_for
from app.stages import group
from app.types import evidence

MAX_FORCE_ERROR = Decimal("0.05")
LEVEL_ORDER = (20, 40, 100)


def _attribution(row, target_day):
    """返回 (营业日, 班次, 依据)。带时刻按 20:00/08:00 切班，无时刻按日期推断。"""
    if row.get("clock"):
        return shift_for(row["day"], row["clock"])
    return attribute(row["day"], target_day)


def align(rows, targets):
    candidates, isolated, repeat_flags = [], [], []

    for (beam, strand, end), values in group(rows, ["beam", "strand", "end"]).items():
        target = targets.get((beam, strand))
        if target is None:
            isolated.extend(evidence(row, "NO_TARGET") for row in values)
            continue
        target_day = target["day"]
        window = (target_day, target_day + timedelta(days=1))
        by_day = {day: day_rows for (day,), day_rows in group(values, ["day"]).items()}
        foreign = [
            row for day, day_rows in by_day.items() if day not in window for row in day_rows
        ]
        isolated.extend(evidence(row, "NO_TARGET") for row in foreign)

        # 次日读数拆成跨零点末级（归本营业日）与可能的第二次张拉（归次日）。
        spillover, second_event = [], []
        for row in by_day.get(target_day + timedelta(days=1), []):
            business_day, _, _ = _attribution(row, target_day)
            (spillover if business_day == target_day else second_event).append(row)
        first_event = by_day.get(target_day, []) + spillover

        first_levels = {row["level"] for row in first_event}
        second_levels = {row["level"] for row in second_event}
        if set(LEVEL_ORDER).issubset(first_levels) and set(LEVEL_ORDER).issubset(second_levels):
            # 两次完整张拉：保留第一次，第二次整组隔离，绝不自动采信后一次。
            for row in second_event:
                business_day, shift_name, basis = _attribution(row, target_day)
                isolated.append(
                    evidence(
                        {**row, "business_day": business_day, "shift": shift_name, "shift_basis": basis},
                        "REPEAT_TENSION",
                    )
                )
                repeat_flags.append((beam, strand, end))
            event_rows = first_event
        else:
            event_rows = [
                row
                for day, day_rows in by_day.items()
                if day in window
                for row in day_rows
            ]

        for row in event_rows:
            business_day, shift_name, basis = _attribution(row, target_day)
            if business_day != target_day:
                isolated.append(evidence(row, "NO_TARGET"))
                continue
            candidate = {
                **row,
                "business_day": business_day,
                "shift": shift_name,
                "shift_basis": basis,
            }
            nominal = target["design"] * row["level"] / 100
            if abs(row["kn"] - nominal) > nominal * MAX_FORCE_ERROR:
                isolated.append(evidence(candidate, "FORCE_TOLERANCE"))
            else:
                candidates.append(candidate)

    aligned = {}
    for key, key_rows in group(candidates, ["beam", "strand", "end", "level"]).items():
        if len(key_rows) == 1:
            aligned[key] = key_rows[0]
        else:
            isolated.extend(evidence(row, "LEVEL_CONFLICT") for row in key_rows)
    return aligned, isolated, sorted(set(repeat_flags))
