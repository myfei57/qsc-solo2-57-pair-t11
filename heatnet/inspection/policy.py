"""不一致发现的处置策略与建议。

发现不一致时是拦住相关动作还是只记审计，按设备类型定死：热源、总管、泵、阀与
换热站这类处在能量通道上的设备，漂移直接危及动作安全，按 ``block`` 处理——
巡检闸门不放开，投运与调度不得下发；流量计、热量表、压力传感器与气象网关这类
量测设备漂移不直接危及机械安全，按 ``record`` 处理——记告警落审计，动作照常。
没有登记策略的新类型从严按 ``block`` 处理；同一发现牵涉声明与实际两个类型时，
取两者中更严的一档。

每条发现都带一份可执行的处置建议：``deregister``（从点表注销）、``register``
（补登记进点表）、``correct-kind``（按实际类型更正点表）、``re-probe``（修复
通讯后重巡）。建议由 :class:`~heatnet.inspection.patrol.Inspector` 的 ``apply``
真正执行，执行后立即复巡，处置与复核都落审计。
"""

from __future__ import annotations

from typing import Mapping

BLOCK = "block"
RECORD = "record"

MISSING = "missing"
EXTRA = "extra"
KIND_MISMATCH = "kind_mismatch"
UNREADABLE = "unreadable"

DEFAULT_POLICY: dict[str, str] = {
    "heat-source": BLOCK,
    "header": BLOCK,
    "pump": BLOCK,
    "control-valve": BLOCK,
    "mix-valve": BLOCK,
    "heat-exchange-station": BLOCK,
    "heat-meter": RECORD,
    "flow-meter": RECORD,
    "pressure-sensor": RECORD,
    "weather-gateway": RECORD,
}


def policy_for(kind: str | None, table: Mapping[str, str] | None = None) -> str:
    """返回某设备类型的处置策略，未知类型从严按 ``block``。"""

    table = DEFAULT_POLICY if table is None else table
    if kind is None:
        return BLOCK
    return table.get(kind, BLOCK)


def strictest(kinds: list[str | None], table: Mapping[str, str] | None = None) -> str:
    """一组牵涉类型里取最严的一档策略；只评实际存在的类型。"""

    policies = [policy_for(kind, table) for kind in kinds if kind is not None]
    if not policies:
        return BLOCK
    return BLOCK if BLOCK in policies else RECORD


def recommendation(
    category: str, address: str, declared_kind: str | None, actual_kind: str | None
) -> dict:
    """按发现类别给出可执行的处置建议。"""

    if category == MISSING:
        return {
            "action": "deregister",
            "params": {"address": address},
            "summary": "现场确认设备已拆除或改址后，从点表注销该点；若只是改址，按新地址重新登记",
        }
    if category == EXTRA:
        return {
            "action": "register",
            "params": {"address": address, "kind": actual_kind},
            "summary": "把现场已存在但未登记的设备补登记进点表，登记前调度与结算不覆盖该设备",
        }
    if category == KIND_MISMATCH:
        return {
            "action": "correct-kind",
            "params": {"address": address, "kind": actual_kind},
            "summary": f"按实际类型 {actual_kind} 更正点表（登记为 {declared_kind}），并核查是否接错线",
        }
    return {
        "action": "re-probe",
        "params": {"address": address},
        "summary": "检查通讯与供电后重新巡检；证据补齐前该点按未确认处理，不能判正常",
    }
