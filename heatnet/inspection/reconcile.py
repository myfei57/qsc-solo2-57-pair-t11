"""声明与实际的逐点核对。

比对方式定死为逐点全量（``census``），不做分组抽样：点表规模有限，全量探测
代价可忽略，而抽样恰恰可能漏掉漂移的那个点；逐点结果按固定顺序产出，前后两次
巡检可以逐点对比，审计口径稳定。读不到的点记 ``unreadable``——缺少证据的设备
不能判正常，本次巡检的证据完整性随之降为 ``partial``，整体结论不为 ``ok``。
"""

from __future__ import annotations

from typing import Mapping

from .plan import Reading
from .policy import (
    DEFAULT_POLICY,
    EXTRA,
    KIND_MISMATCH,
    MISSING,
    UNREADABLE,
    recommendation,
    strictest,
)

STRATEGY = "census"

CATEGORIES = (MISSING, EXTRA, KIND_MISMATCH, UNREADABLE)


def _describe(category: str, point: dict) -> str:
    if category == MISSING:
        return "点表登记了该点，现场不存在"
    if category == EXTRA:
        return "现场存在该设备，点表未登记"
    if category == KIND_MISMATCH:
        return f"类型不符：点表 {point['declared_kind']}，实际 {point['actual_kind']}"
    return "该点读不到，缺少证据"


def _finding(category: str, point: dict, error: str | None, policy: Mapping[str, str]) -> dict:
    kinds = [point["declared_kind"], point["actual_kind"]]
    return {
        "category": category,
        "address": point["address"],
        "declared_kind": point["declared_kind"],
        "actual_kind": point["actual_kind"],
        "policy": strictest(kinds, policy),
        "detail": error if error else _describe(category, point),
        "recommendation": recommendation(
            category, point["address"], point["declared_kind"], point["actual_kind"]
        ),
    }


def reconcile(
    declared: dict[str, str],
    readings: list[Reading],
    policy: Mapping[str, str] | None = None,
) -> dict:
    """把声明点表与实际探测结果逐点对齐，返回核对结果。"""

    table = dict(DEFAULT_POLICY if policy is None else policy)
    points: list[dict] = []
    findings: list[dict] = []

    for reading in readings:
        probe = reading.probe
        declared_kind = declared.get(probe.address)
        if declared_kind is None:
            status = EXTRA
        elif not reading.ok:
            status = UNREADABLE
        elif declared_kind != probe.kind:
            status = KIND_MISMATCH
        else:
            status = "ok"
        point: dict = {
            "address": probe.address,
            "area": probe.area,
            "status": status,
            "declared_kind": declared_kind,
            "actual_kind": probe.kind,
        }
        if reading.ok:
            point["evidence"] = reading.evidence
        else:
            point["error"] = reading.error
        points.append(point)
        if status != "ok":
            findings.append(_finding(status, point, reading.error, table))

    covered = {reading.probe.address for reading in readings}
    for address in sorted(set(declared) - covered):
        point = {
            "address": address,
            "area": address.split(".", 1)[0],
            "status": MISSING,
            "declared_kind": declared[address],
            "actual_kind": None,
        }
        points.append(point)
        findings.append(_finding(MISSING, point, None, table))

    counts = {category: 0 for category in CATEGORIES}
    counts["ok"] = 0
    for point in points:
        counts[point["status"]] += 1
    evidence = "partial" if counts[UNREADABLE] else "complete"
    return {
        "strategy": STRATEGY,
        "evidence": evidence,
        "ok": evidence == "complete" and not findings,
        "counts": counts,
        "points": points,
        "findings": findings,
    }
