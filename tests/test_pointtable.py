"""点表巡检：声明对实际、按类型定拦或记、部分失败与证据规则。"""

from __future__ import annotations

import json

import pytest

from heatnet.app import build_platform
from heatnet.cli import main
from heatnet.clock import ManualClock
from heatnet.config import default_config
from heatnet.console.api import Api
from heatnet.errors import InterlockError, NamespaceError
from heatnet.pointtable import FieldPoint

AREA_ORDER = ["plant", "primary", "secondary", "station", "valve", "quota"]


def test_clean_platform_inspects_ok(platform):
    report = platform.run_inspection()
    assert report["ok"] is True
    assert report["verdict"] == "ok"
    assert report["method"] == "full-census"
    assert report["order"] == AREA_ORDER
    assert report["findings"] == []
    assert report["blocked_operations"] == []
    totals = report["totals"]
    assert totals["declared"] == totals["actual"] == totals["probed"]
    assert totals["declared"] == platform.namespaces.describe()["count"]


def test_probe_order_follows_dispatch_chain(platform):
    report = platform.run_inspection()
    areas = [reading["address"].split(".", 1)[0] for reading in report["readings"]]
    assert areas == sorted(areas, key=AREA_ORDER.index)


def test_missing_device_blocks_related_actions(platform):
    platform.inventory.remove("station.st02")
    report = platform.run_inspection()
    assert report["ok"] is False
    assert report["verdict"] == "mismatch"
    finding = report["findings"][0]
    assert finding["class"] == "missing"
    assert finding["address"] == "station.st02"
    assert finding["policy"] == "block"
    assert finding["remedy"]["op"] == "deregister"
    assert "dispatch" in report["blocked_operations"]
    with pytest.raises(InterlockError):
        platform.dispatch(60.0, 60.0)


def test_extra_unregistered_device_is_reported(platform):
    platform.inventory.add(
        FieldPoint("station", "st09", "heat-exchange-station", lambda: {"zone": "north"})
    )
    report = platform.run_inspection()
    assert report["verdict"] == "mismatch"
    finding = report["findings"][0]
    assert finding["class"] == "extra"
    assert finding["address"] == "station.st09"
    assert finding["policy"] == "block"
    assert finding["remedy"]["op"] == "register"
    assert finding["remedy"]["kind"] == "heat-exchange-station"


def test_type_mismatch_reports_correction(platform):
    platform.inventory.set_kind("valve.st01.mix", "control-valve")
    report = platform.run_inspection()
    assert report["verdict"] == "mismatch"
    finding = report["findings"][0]
    assert finding["class"] == "type_mismatch"
    assert finding["declared_kind"] == "mix-valve"
    assert finding["actual_kind"] == "control-valve"
    assert finding["policy"] == "block"
    assert finding["remedy"]["op"] == "correct-kind"
    assert finding["remedy"]["actual"] == "control-valve"


def test_unverified_point_is_partial_failure_not_normal(platform):
    platform.inventory.set_online("quota.st01.heat-meter", False)
    report = platform.run_inspection()
    assert report["ok"] is False
    assert report["verdict"] == "partial"
    finding = report["findings"][0]
    assert finding["class"] == "unverified"
    assert finding["policy"] == "record"
    assert finding["remedy"]["op"] == "re-probe"
    assert report["blocked_operations"] == []
    outcome = platform.collect_heat("st01.heat-meter", 1.0)
    assert outcome["meter"] == "st01.heat-meter"


def test_unverified_actuator_blocks_related_actions(platform):
    platform.inventory.set_online("valve.st01.mix", False)
    report = platform.run_inspection()
    assert report["verdict"] == "partial"
    assert "queue" in report["blocked_operations"]
    assert "dispatch" in report["blocked_operations"]
    with pytest.raises(InterlockError):
        platform.queue_commands("st01", [50.0])


def test_missing_meter_records_but_does_not_block(platform):
    platform.inventory.remove("quota.st01.heat-meter")
    report = platform.run_inspection()
    assert report["verdict"] == "mismatch"
    assert report["blocked_operations"] == []
    finding = report["findings"][0]
    assert finding["class"] == "missing"
    assert finding["policy"] == "record"
    outcome = platform.collect_heat("st01.heat-meter", 1.0)
    assert outcome["meter"] == "st01.heat-meter"


def test_mismatch_outranks_partial(platform):
    platform.inventory.remove("station.st02")
    platform.inventory.set_online("quota.st01.heat-meter", False)
    report = platform.run_inspection()
    assert report["verdict"] == "mismatch"
    assert report["totals"]["missing"] == 1
    assert report["totals"]["unverified"] == 1
    assert report["ok"] is False


def test_remedy_and_reinspection_release_the_latch(platform):
    platform.start()
    platform.push_weather(-8.0)
    platform.startup(-8.0, 60.0)
    platform.inventory.remove("station.st02")
    platform.run_inspection()
    with pytest.raises(InterlockError):
        platform.dispatch(60.0, 60.0)
    outcome = platform.apply_remedy({"op": "deregister", "address": "station.st02"})
    assert outcome["deregistered"] == "station.st02"
    cleared = platform.run_inspection()
    assert cleared["ok"] is True
    report = platform.dispatch(60.0, 60.0)
    assert report["ok"] is True


def test_startup_refreshes_inspection_and_blocks(platform):
    platform.inventory.remove("station.st01")
    with pytest.raises(InterlockError):
        platform.startup(-8.0, 60.0)
    blocked = [entry for entry in platform.audit.alarms() if entry["action"] == "inspect_blocked"]
    assert blocked
    assert blocked[-1]["payload"]["operation"] == "startup"


def test_inspection_writes_audit_and_persists(platform):
    platform.inventory.set_kind("valve.st01.mix", "control-valve")
    report = platform.run_inspection()
    assert report["verdict"] == "mismatch"
    alarms = platform.audit.alarms()
    assert any(entry["action"] == "inspect" and entry["severity"] == "alarm" for entry in alarms)
    assert any(
        entry["action"] == "inspect_finding" and entry["asset"] == "valve.st01.mix"
        for entry in alarms
    )
    stored = platform.store.read("inspection/latest")
    assert stored["verdict"] == "mismatch"
    assert stored["findings"][0]["address"] == "valve.st01.mix"


def test_inspection_latch_survives_restart(tmp_path):
    root = str(tmp_path / "state")
    platform = build_platform(default_config(), clock=ManualClock(), storage_root=root)
    platform.inventory.remove("station.st02")
    assert platform.run_inspection()["verdict"] == "mismatch"
    rebuilt = build_platform(default_config(), clock=ManualClock(), storage_root=root)
    view = rebuilt.inspection_report()
    assert view["latest"]["verdict"] == "mismatch"
    assert "dispatch" in view["blocked_operations"]
    with pytest.raises(InterlockError):
        rebuilt.dispatch(60.0, 60.0)


def test_periodic_inspection_runs_every_n_cycles(tmp_path):
    platform = build_platform(
        default_config(),
        clock=ManualClock(),
        storage_root=str(tmp_path / "state"),
        inspect_period_cycles=3,
    )
    platform.cycle(dt=1.0)
    platform.cycle(dt=1.0)
    assert platform.inspection_report()["latest"] is None
    platform.cycle(dt=1.0)
    latest = platform.inspection_report()["latest"]
    assert latest is not None
    assert latest["origin"] == "periodic"
    assert latest["ok"] is True


def test_inspection_is_read_only(platform):
    platform.queue_commands("st01", [55.0])
    platform.replay_valves(["st01"])
    before = platform.valves["st01"].position_pct()
    platform.run_inspection()
    assert platform.valves["st01"].position_pct() == pytest.approx(before)


def test_registry_supports_remedy_operations(platform):
    table = platform.namespaces.table()
    assert table["valve.st01.mix"] == "mix-valve"
    device = platform.namespaces.correct_kind("valve.st01.mix", "control-valve")
    assert device.kind == "control-valve"
    removed = platform.namespaces.deregister("valve.st01.mix")
    assert removed.address == "valve.st01.mix"
    with pytest.raises(NamespaceError):
        platform.namespaces.deregister("valve.st01.mix")


def test_console_exposes_inspection_and_remedy(platform):
    api = Api(platform)
    status, report = api.handle("POST", "/api/inspect", {}, {})
    assert status == 200
    assert report["ok"] is True
    status, view = api.handle("GET", "/api/inspection", {}, {})
    assert status == 200
    assert view["method"] == "full-census"
    assert view["order"] == AREA_ORDER
    assert view["policy"]["mix-valve"] == "block"
    assert view["policy"]["heat-meter"] == "record"
    assert view["latest"]["verdict"] == "ok"

    platform.inventory.remove("station.st02")
    status, report = api.handle("POST", "/api/inspect", {}, {})
    assert report["ok"] is False
    remedy = report["findings"][0]["remedy"]
    assert remedy["op"] == "deregister"
    status, payload = api.handle("POST", "/api/dispatch", {}, {"demand_pct": 60.0})
    assert status == 409
    assert payload["component"] == "pointtable"
    status, outcome = api.handle("POST", "/api/inspection/remedy", {}, remedy)
    assert status == 200
    assert outcome["deregistered"] == "station.st02"
    status, again = api.handle("POST", "/api/inspect", {}, {})
    assert again["ok"] is True
    status, bad = api.handle("POST", "/api/inspection/remedy", {}, {"op": "nope"})
    assert status == 400


def test_inspect_command_reports_verdict(tmp_path, capsys):
    exit_code = main(["inspect", "--storage-root", str(tmp_path / "state")])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["verdict"] == "ok"
    assert payload["method"] == "full-census"


def test_demo_with_drift_repairs_and_passes(tmp_path, capsys):
    exit_code = main(
        [
            "demo",
            "--fast",
            "--cycles",
            "20",
            "--rounds",
            "8",
            "--drift",
            "--storage-root",
            str(tmp_path / "state"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["inspection"]["ok"] is True
    assert payload["inspection"]["verdict"] == "ok"
