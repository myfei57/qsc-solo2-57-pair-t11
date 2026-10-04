"""点表巡检。

现场点表（:class:`~heatnet.ns.registry.NamespaceRegistry`）是装机时登记的"声明侧"，
本包维护"实际侧"清单并定期把两侧逐点对一遍：列出多出来的、少掉的、类型写错的
和读不到证据的，每条发现都带一条能直接执行的处置建议。比对方式、巡检顺序与
"按设备类型决定拦还是记"的处置策略都定死在 :mod:`~heatnet.pointtable.policy`，
巡检编排与判定规则在 :mod:`~heatnet.pointtable.inspection`。
"""

from __future__ import annotations

from .diff import EXTRA, MISSING, TYPE_MISMATCH, UNVERIFIED, Finding, diff_points
from .inspection import MISMATCH, OK, PARTIAL, run_inspection, severity_of
from .policy import AREAS, BLOCK, KIND_POLICY, METHOD, OPERATION_AREAS, RECORD, blocked_operations, policy_for
from .probe import FieldInventory, FieldPoint, ProbeReading

__all__ = [
    "AREAS",
    "BLOCK",
    "EXTRA",
    "FieldInventory",
    "FieldPoint",
    "Finding",
    "KIND_POLICY",
    "METHOD",
    "MISMATCH",
    "MISSING",
    "OK",
    "OPERATION_AREAS",
    "PARTIAL",
    "ProbeReading",
    "RECORD",
    "TYPE_MISMATCH",
    "UNVERIFIED",
    "blocked_operations",
    "diff_points",
    "policy_for",
    "run_inspection",
    "severity_of",
]
