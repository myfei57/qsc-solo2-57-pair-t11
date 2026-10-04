"""声明与实际的逐点比对。

产出四类发现：``missing``（点表有、现场没有）、``extra``（现场有、点表没登记）、
``type_mismatch``（两边都有但类型不一致）、``unverified``（点读不到、证据缺失，
不能判正常）。每条发现都带一条能直接执行的处置建议（注销 / 补登 / 更正类型 /
复巡），建议里的操作名与命名空间注册表的方法一一对应。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .policy import AREAS, policy_for, stricter
from .probe import ProbeReading

MISSING = "missing"
EXTRA = "extra"
TYPE_MISMATCH = "type_mismatch"
UNVERIFIED = "unverified"

_CLASSES = (MISSING, EXTRA, TYPE_MISMATCH, UNVERIFIED)


@dataclass(frozen=True)
class Finding:
    """一条声明与实际不一致的发现。"""

    cls: str
    address: str
    area: str
    declared_kind: str
    actual_kind: str
    policy: str
    message: str
    remedy: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "class": self.cls,
            "address": self.address,
            "area": self.area,
            "declared_kind": self.declared_kind or None,
            "actual_kind": self.actual_kind or None,
            "policy": self.policy,
            "message": self.message,
            "remedy": dict(self.remedy),
            "evidence": dict(self.evidence),
        }


def _area_of(address: str) -> str:
    return address.split(".", 1)[0]


def _missing(address: str, kind: str) -> Finding:
    return Finding(
        MISSING,
        address,
        _area_of(address),
        kind,
        "",
        policy_for(kind),
        f"点表登记了 {address}（{kind}），现场不存在该设备",
        remedy={
            "op": "deregister",
            "address": address,
            "note": "现场确认已拆除后从点表注销该地址；若只是改址，按新地址重新登记",
        },
    )


def _extra(address: str, kind: str) -> Finding:
    area, device = address.split(".", 1)
    return Finding(
        EXTRA,
        address,
        area,
        "",
        kind,
        policy_for(kind),
        f"现场存在 {address}（{kind}），点表未登记",
        remedy={
            "op": "register",
            "area": area,
            "device": device,
            "kind": kind,
            "note": "把设备补登进点表；若非本单位设备，按私接处置",
        },
    )


def _type_mismatch(address: str, declared: str, actual: str, evidence: dict) -> Finding:
    return Finding(
        TYPE_MISMATCH,
        address,
        _area_of(address),
        declared,
        actual,
        stricter(policy_for(declared), policy_for(actual)),
        f"{address} 点表类型 {declared} 与现场实际 {actual} 不一致",
        remedy={
            "op": "correct-kind",
            "address": address,
            "declared": declared,
            "actual": actual,
            "note": "按现场实际类型更正点表登记；若现场接错设备，先纠正接线",
        },
        evidence=evidence,
    )


def _unverified(address: str, kind: str, error: str) -> Finding:
    return Finding(
        UNVERIFIED,
        address,
        _area_of(address),
        kind,
        "",
        policy_for(kind),
        f"{address} 读取失败（{error}），缺少证据，不能判为正常",
        remedy={
            "op": "re-probe",
            "address": address,
            "note": "恢复通讯后重新巡检；证据补齐前该设备不得判为正常",
        },
        evidence={"error": error},
    )


def diff_points(declared: dict[str, str], readings: list[ProbeReading]) -> list[Finding]:
    """逐点全量比对声明表与现场读数，返回按巡检顺序排序的发现。"""

    actual = {reading.address: reading for reading in readings}
    findings: list[Finding] = []
    for address, kind in declared.items():
        reading = actual.get(address)
        if reading is None:
            findings.append(_missing(address, kind))
        elif not reading.ok:
            findings.append(_unverified(address, kind, reading.error or "读取失败"))
        elif reading.kind != kind:
            findings.append(_type_mismatch(address, kind, reading.kind, reading.evidence))
    for address, reading in actual.items():
        if address not in declared:
            findings.append(_extra(address, reading.kind))
    rank = {area: index for index, area in enumerate(AREAS)}
    findings.sort(key=lambda item: (rank.get(item.area, len(rank)), item.address, _CLASSES.index(item.cls)))
    return findings
