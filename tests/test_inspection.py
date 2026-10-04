"""点表巡检：声明与实际逐点核对、闸门、处置与审计一致性。"""

from __future__ import annotations

import pytest

from heatnet.console.api import Api
from heatnet.errors import PlantError
from heatnet.inspection.plan import PROBE_ORDER
from heatnet.quota.meter import HeatMeter


def _find(report: dict, category: str) -> dict:
    return next(item for item in report["findings"] if item["category"] == category)


def test_clean_patrol_passes_and_orders_points(platform):
    report = platform.inspect_now()
    assert report["ok"] is True
    assert report["evidence"] == "complete"
    assert report["strategy"] == "census"
    assert report["counts"]["ok"] == report["declared"]["count"] == 25
    assert report["actual"]["count"] == 25
    order = {area: index for index, area in enumerate(PROBE_ORDER)}
    ranks = [order[point["area"]] for point in report["points"]]
    assert ranks == sorted(ranks)
    gate = platform.inspection.gate()
    assert gate["open"] is True
    assert gate["blocks"] == []


def test_gate_stays_closed_without_any_evidence(platform):
    gate = platform.inspection.gate()
    assert gate["open"] is False
    assert gate["reason"] == "no-evidence"


def test_missing_declared_device_blocks_startup(platform):
    platform.namespaces.register("station", "ghost", "heat-exchange-station")
    report = platform.inspect_now()
    assert report["ok"] is False
    finding = _find(report, "missing")
    assert finding["address"] == "station.ghost"
    assert finding["policy"] == "block"
    assert finding["recommendation"]["action"] == "deregister"

    launch = platform.startup(-8.0, 60.0)
    assert launch["ok"] is False
    assert launch["stage"] == "inspection"
    assert launch["violations"] == ["inspection_block:station.ghost"]
    assert platform.audit.count("interlock_rejected") >= 1
    drifts = [entry for entry in platform.audit.entries(limit=50) if entry["action"] == "drift"]
    assert drifts
    assert drifts[0]["severity"] == "alarm"
    assert drifts[0]["asset"] == "station.ghost"


def test_extra_meter_is_recorded_not_blocked(platform):
    platform.meters.register(HeatMeter("st09.heat-meter", 100000.0))
    report = platform.inspect_now()
    assert report["ok"] is False
    finding = _find(report, "extra")
    assert finding["address"] == "quota.st09.heat-meter"
    assert finding["policy"] == "record"
    assert finding["recommendation"]["action"] == "register"
    assert platform.inspection.gate()["open"] is True

    launch = platform.startup(-8.0, 60.0)
    assert launch["ok"] is True
    drifts = [entry for entry in platform.audit.entries(limit=50) if entry["action"] == "drift"]
    assert drifts
    assert all(entry["severity"] == "warning" for entry in drifts)


def test_kind_mismatch_flagged_and_corrected(platform):
    platform.namespaces.correct_kind("valve.st01.mix", "control-valve")
    report = platform.inspect_now()
    assert report["ok"] is False
    finding = _find(report, "kind_mismatch")
    assert finding["address"] == "valve.st01.mix"
    assert finding["declared_kind"] == "control-valve"
    assert finding["actual_kind"] == "mix-valve"
    assert finding["recommendation"]["action"] == "correct-kind"

    applied = platform.apply_disposition("valve.st01.mix")
    assert applied["applied"]["action"] == "correct-kind"
    assert applied["report"]["ok"] is True
    assert platform.namespaces.resolve("valve.st01.mix").kind == "mix-valve"


def test_unreadable_point_is_partial_failure(platform, monkeypatch):
    def broken() -> dict:
        raise RuntimeError("comm-timeout")

    monkeypatch.setattr(platform.stations["st01"], "snapshot", broken)
    report = platform.inspect_now()
    assert report["ok"] is False
    assert report["evidence"] == "partial"
    point = next(item for item in report["points"] if item["address"] == "station.st01")
    assert point["status"] == "unreadable"
    assert "comm-timeout" in point["error"]
    assert report["counts"]["unreadable"] == 1
    assert report["counts"]["ok"] == report["declared"]["count"] - 1
    assert platform.inspection.gate()["open"] is False


def test_disposition_deregisters_ghost_and_reopens_gate(platform):
    platform.namespaces.register("station", "ghost", "heat-exchange-station")
    platform.inspect_now()
    assert platform.inspection.gate()["open"] is False

    applied = platform.apply_disposition("station.ghost")
    assert applied["applied"]["action"] == "deregister"
    assert applied["report"]["ok"] is True
    assert platform.inspection.gate()["open"] is True
    with pytest.raises(PlantError):
        platform.namespaces.resolve("station.ghost")
    launch = platform.startup(-8.0, 60.0)
    assert launch["ok"] is True


def test_disposition_registers_extra_meter(platform):
    platform.meters.register(HeatMeter("st09.heat-meter", 100000.0))
    platform.inspect_now()
    applied = platform.apply_disposition("quota.st09.heat-meter")
    assert applied["applied"]["action"] == "register"
    assert applied["report"]["ok"] is True
    device = platform.namespaces.resolve("quota.st09.heat-meter")
    assert device.kind == "heat-meter"
    assert device.area == "quota"


def test_apply_without_findings_is_rejected(platform):
    with pytest.raises(PlantError):
        platform.apply_disposition("station.st01")
    platform.inspect_now()
    with pytest.raises(PlantError):
        platform.apply_disposition("station.st01")
    with pytest.raises(PlantError):
        platform.apply_disposition("")


def test_dispatch_blocked_by_block_drift(platform):
    platform.namespaces.register("station", "ghost", "heat-exchange-station")
    platform.inspect_now()
    report = platform.dispatch(60.0, 60.0)
    assert report["ok"] is False
    assert report["stage"] == "inspection"
    assert report["violations"] == ["inspection_block:station.ghost"]
    assert platform.network.dispatches() == 0


def test_start_runs_preflight_patrol(platform):
    payload = platform.start()
    assert payload["inspection"]["ok"] is True
    assert payload["inspection"]["counts"]["ok"] == 25
    status = platform.status()
    assert status["inspection"]["gate"]["open"] is True
    assert status["inspection"]["latest"]["ok"] is True


def test_console_inspection_matches_audit(platform):
    api = Api(platform)
    status, payload = api.handle("POST", "/api/inspection/run", {}, {})
    assert status == 200
    run_id = payload["run_id"]

    status, shown = api.handle("GET", "/api/inspection", {}, {})
    assert status == 200
    assert shown["report"]["run_id"] == run_id
    assert shown["gate"]["open"] is True
    assert shown["strategy"] == "census"
    patrols = [entry for entry in platform.audit.entries(limit=100) if entry["action"] == "patrol"]
    assert patrols
    assert patrols[0]["payload"]["run_id"] == run_id

    platform.namespaces.register("station", "ghost", "heat-exchange-station")
    status, drifted = api.handle("POST", "/api/inspection/run", {}, {})
    assert status == 200
    assert drifted["ok"] is False
    status, applied = api.handle(
        "POST", "/api/inspection/apply", {}, {"address": "station.ghost"}
    )
    assert status == 200
    assert applied["report"]["ok"] is True
    status, rejected = api.handle(
        "POST", "/api/inspection/apply", {}, {"address": "station.ghost"}
    )
    assert status == 409
    assert rejected["component"] == "inspection"
