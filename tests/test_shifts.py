import json
from datetime import date
from io import BytesIO

import pytest

from app.modules.m1_sampling.source import load
from app.modules.m3_alignment.shifts import shift_for
from app.modules.m7_runs.service import calculate
from app.modules.m7_runs.store import History
from app.modules.m7_runs.service import run_once


@pytest.fixture(scope="session")
def night():
    from app.config import BASE

    return (BASE / "sample_data" / "night.json").read_bytes()


@pytest.fixture(scope="session")
def night_report(night):
    return calculate(night)


def test_night_shift_window_assignment():
    # 20:00 开工归当日，00:40 跨零点归前一营业日，08:00 边界含在白班。
    d = date(2026, 11, 20)
    assert shift_for(d, "20:00")[:2] == (d, "夜班")
    assert shift_for(date(2026, 11, 21), "00:40")[:2] == (d, "夜班")
    assert shift_for(date(2026, 11, 21), "07:59")[:2] == (d, "夜班")
    assert shift_for(date(2026, 11, 21), "08:00")[:2] == (date(2026, 11, 21), "白班")


def test_cross_midnight_strand_keeps_one_business_day(night_report):
    s01 = next(r for r in night_report["判验"] if r["钢束"] == "S01")
    assert (s01["营业日"], s01["判验"], s01["合计毫米"]) == ("2026-11-20", "通过", "41.000")
    levels = [r for r in night_report["力级记录"] if r["钢束"] == "S01" and r["端位"] == "L"]
    assert {r["营业日"] for r in levels} == {"2026-11-20"}
    peak = next(r for r in levels if r["力级%"] == 100)
    assert (peak["记录日"], peak["班次"], peak["班次依据"]) == (
        "2026-11-21",
        "夜班",
        "跨零点归入前一营业日",
    )


def test_date_only_cross_midnight_inferred(night_report):
    rows = [r for r in night_report["力级记录"] if r["钢束"] == "S02" and r["力级%"] == 100]
    assert rows and all(r["时刻"] is None for r in rows)
    assert all(r["营业日"] == "2026-11-20" and "跨零点" in r["班次依据"] for r in rows)


def test_two_complete_sets_are_two_tensionings(night_report):
    s02 = next(r for r in night_report["判验"] if r["钢束"] == "S02")
    assert s02["判验"] == "待复测"
    assert s02["证据"] == ["L-REPEAT_TENSION", "R-REPEAT_TENSION"]
    repeats = [r for r in night_report["隔离"] if r["原因码"] == "REPEAT_TENSION"]
    assert len(repeats) == 6
    # 后一次张拉的每条隔离读数都带班次依据，且不被自动采信
    assert all(r["班次依据"] and r["营业日"] == "2026-11-21" for r in repeats)
    accepted_s02 = [r for r in night_report["力级记录"] if r["钢束"] == "S02"]
    assert {r["记录日"] for r in accepted_s02} == {"2026-11-20", "2026-11-21"}
    assert all(r["营业日"] == "2026-11-20" for r in accepted_s02)


def test_repeat_tension_conservation(night_report):
    balance = night_report["读数勾稽"]
    assert balance["原读数"] == balance["对齐"] + balance["隔离"] + balance["重复"] == 18
    assert balance["行差"] == 0


def test_export_contains_shift_rules_and_basis(night):
    report = calculate(night)
    rules = {row["规则"] for row in report["班次规则"]}
    assert {"营业日切分", "跨零点归属", "重复张拉"} <= rules
    assert all("营业日" in row for row in report["判验"])
    assert all("班次依据" in row for row in report["力级记录"])


def test_clock_field_optional_and_validated(checked):
    content = load(checked)
    content["readings"][0]["clock"] = "25:00"
    report = calculate(json.dumps(content).encode())
    assert report["隔离"][0]["原因码"] == "BAD_READING"
    content["readings"][0]["clock"] = "21:30"
    report = calculate(json.dumps(content).encode())
    assert report["力级记录"][0]["班次"] == "夜班"


def test_foreign_day_still_no_target(checked):
    content = load(checked)
    content["readings"][0]["day"] = "2026-11-19"
    assert calculate(json.dumps(content).encode())["隔离"][0]["原因码"] == "NO_TARGET"


def test_incomplete_second_set_does_not_trigger_repeat(checked):
    # 次日只补一条 100% 且无时刻：属于跨零点末级，整束仍是一次张拉
    content = load(checked)
    extra = dict(content["readings"][2])
    extra["day"] = "2026-11-21"
    extra["id"] = "cross-midnight-peak"
    content["readings"][2]["day"] = "2026-11-21"
    content["readings"][5]["day"] = "2026-11-21"
    content["readings"].append(extra)
    report = calculate(json.dumps(content).encode())
    assert not [r for r in report["隔离"] if r["原因码"] == "REPEAT_TENSION"]


def test_rerun_same_batch_adds_no_version(client, night):
    first = client.post("/api/runs", data={"file": (BytesIO(night), "night.json")})
    second = client.post("/api/runs", data={"file": (BytesIO(night), "night.json")})
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json["id"] == second.json["id"]
    assert len(client.get("/api/runs").json) == 1


def test_failed_recalc_keeps_old_version(tmp_path, night, checked):
    db = tmp_path / "keep.sqlite"
    history = History(db)
    old, reused = run_once(history, night)
    assert reused is False
    with pytest.raises(Exception):
        run_once(history, b"{broken json")
    still = history.find(old["清单"]["编号"])
    assert still is not None and still["清单"]["编号"] == old["清单"]["编号"]
    # 完好的其他批次仍可正常入库
    other, reused = run_once(history, checked)
    assert reused is False and other["清单"]["编号"] != old["清单"]["编号"]
