import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from time import perf_counter

from app.config import VERSION
from app.modules.m1_sampling.service import accept
from app.modules.m1_sampling.source import load
from app.modules.m2_calibration.registry import calibrations
from app.modules.m2_calibration.service import convert
from app.modules.m3_alignment.service import align
from app.modules.m3_alignment.targets import parse_targets
from app.modules.m4_elongation.service import compensate
from app.modules.m5_verdicts.service import classify
from app.modules.m6_reconcile.service import ledger
from app.stages import label


def digest(data):
    return hashlib.sha256(data).hexdigest()


def serialized(value):
    if isinstance(value, Decimal):
        return label(value)
    if value is None:
        return None
    return value.isoformat()


def calculate(data):
    began = perf_counter()
    payload = load(data)
    records, first_issues, duplicates = accept(payload["readings"])
    registry = calibrations(payload["calibrations"])
    targets = parse_targets(payload["targets"])
    forces, calibration_issues = convert(records, registry)
    aligned, force_issues, repeat_tensions = align(forces, targets)
    measurements = compensate(aligned, targets, repeat_tensions)
    verdicts = classify(targets, measurements)
    issues = sorted(first_issues + calibration_issues + force_issues, key=lambda row: row["源行"])
    conservation, beams = ledger(len(payload["readings"]), aligned, issues, duplicates, verdicts)
    output = {
        "清单": {
            "编号": digest(VERSION.encode() + data)[:24],
            "摘要": digest(data),
            "规则": VERSION,
            "计算时间": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "时区": "Asia/Shanghai",
            "耗时毫秒": round((perf_counter() - began) * 1000),
        },
        "班次规则": [
            {"规则": "营业日切分", "说明": "夜班 20:00 至次日 08:00 归开工当日为一个营业日；白班 08:00 至 20:00 归自然日。"},
            {"规则": "跨零点归属", "说明": "无时刻读数落在营业日次日时，按夜班跨零点归入前一营业日，同一钢束三力级留在同一营业日。"},
            {"规则": "重复张拉", "说明": "同一端在营业日当日与次日各有完整三力级时判为两次张拉；后一次整组隔离（REPEAT_TENSION），不自动采信。"},
            {"规则": "缺时刻兜底", "说明": "读数无 clock 字段时按记录日推断并在班次依据中标注；带 clock 时按 20:00/08:00 精确切班。"},
        ],
        "原始采信": [
            {
                "源行": r["line"],
                "梁号": r["beam"],
                "钢束": r["strand"],
                "端位": r["end"],
                "记录日": r["day"],
                "时刻": r.get("clock"),
                "位移毫米": r["stroke"],
                "读数": r["force"],
                "单位": r["unit"],
            }
            for r in records
        ],
        "标定依据": [
            {
                "千斤顶": r["jack"],
                "版本": r["revision"],
                "生效日": r["start"],
                "截止日": r["end"],
                "斜率": r["slope"],
                "截距": r["offset"],
            }
            for r in registry
        ],
        "力级记录": [
            {
                "源行": r["line"],
                "梁号": r["beam"],
                "钢束": r["strand"],
                "端位": r["end"],
                "力级%": r["level"],
                "记录日": r["day"],
                "时刻": r.get("clock"),
                "营业日": r["business_day"],
                "班次": r["shift"],
                "班次依据": r["shift_basis"],
                "载荷千牛": r["kn"],
                "采信来源": r["revision"],
            }
            for r in aligned.values()
        ],
        "补偿记录": [
            {"梁号": key[0], "钢束": key[1], "端位": key[2], **r} for key, r in measurements.items()
        ],
        "判验": verdicts,
        "读数勾稽": conservation,
        "梁号勾稽": beams,
        "隔离": issues,
        "重复": duplicates,
    }
    return json.loads(json.dumps(output, default=serialized, ensure_ascii=False))


def run_once(history, data):
    key = digest(VERSION.encode() + data)[:24]
    existing = history.find(key)
    return (existing, True) if existing is not None else history.publish(key, calculate(data))
