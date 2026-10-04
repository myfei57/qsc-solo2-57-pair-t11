"""巡检处置策略（定死的部分，改动需要评审而不是现场临时决定）。

- **比对方式**：逐点全量核对，不按分组抽样。点表规模在几十点量级，全量成本
  可以忽略；而加站、改址、换型恰恰是单点漂移，抽样会把要查的东西漏掉，审计
  也需要一份全量清单才能作为依据。
- **巡检顺序**：沿调度链 热源/气象 → 一次网 → 二次网 → 换热站 → 阀门 → 热量，
  与投运依赖方向一致，区域内按地址排序。
- **拦还是记**：按设备类型定。执行链上的设备（热源、母管、泵、阀、换热站）
  不一致时先拦住相关动作；计量与传感类只记录不拦。未知类型按拦处理——
  认不出的设备宁可误拦，不能放行。
"""

from __future__ import annotations

METHOD = "full-census"

AREAS: tuple[str, ...] = ("plant", "primary", "secondary", "station", "valve", "quota")

BLOCK = "block"
RECORD = "record"

KIND_POLICY: dict[str, str] = {
    "heat-source": BLOCK,
    "header": BLOCK,
    "pump": BLOCK,
    "control-valve": BLOCK,
    "mix-valve": BLOCK,
    "heat-exchange-station": BLOCK,
    "weather-gateway": RECORD,
    "flow-meter": RECORD,
    "pressure-sensor": RECORD,
    "heat-meter": RECORD,
}

# 每个操作依赖哪些区域的设备；命中带 block 发现的区域即被拦住。
# 控制循环（cycle）不在表里：它是安全回路，巡检锁存只拦操作类动作。
OPERATION_AREAS: dict[str, tuple[str, ...]] = {
    "weather": ("plant",),
    "adjust": ("plant", "primary"),
    "startup": ("plant", "primary", "secondary", "station", "valve"),
    "shutdown": ("plant", "primary", "secondary", "station", "valve"),
    "dispatch": ("primary", "station", "valve"),
    "queue": ("station", "valve"),
    "replay": ("station", "valve"),
    "secondary_cycle": ("secondary",),
    "pump": ("secondary",),
    "retrofit": ("secondary",),
    "meter": ("quota",),
}


def policy_for(kind: str) -> str:
    """返回某设备类型的处置策略；未知类型按拦处理。"""

    return KIND_POLICY.get(kind, BLOCK)


def stricter(*policies: str) -> str:
    """多个策略取更严的一个。"""

    return BLOCK if BLOCK in policies else RECORD


def blocked_operations(findings: list[dict]) -> list[str]:
    """按当前未消除的发现，推出哪些操作应被拦住。"""

    blocked: list[str] = []
    for operation, areas in OPERATION_AREAS.items():
        if any(finding["policy"] == BLOCK and finding["area"] in areas for finding in findings):
            blocked.append(operation)
    return sorted(blocked)
