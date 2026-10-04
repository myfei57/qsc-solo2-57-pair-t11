"""巡检探测计划。

巡检有固定的先后顺序：按调度链 热源侧 → 一次网 → 二次网 → 换热站 → 阀门 → 计量
依次推进，同一段内按地址排序，每次巡检的探测顺序一致，审计回放可以复现。计划
从活着的运行对象生成——它就是"实际"这一侧；读数只取快照，巡检全程不写设备
状态。某个点读不到时，失败原因原样留在 :class:`Reading` 里，绝不当成正常。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..primary.network import PrimaryNetwork
from ..pump.pump import Pump
from ..quota.accumulator import QuotaAccumulator
from ..secondary.loop import SecondaryLoop
from ..source.source import HeatSource
from ..station.station import HeatStation
from ..temp.curve import HeatCurve
from ..valve.valve import Valve

PROBE_ORDER = ("plant", "primary", "secondary", "station", "valve", "quota")


@dataclass(frozen=True)
class Probe:
    """一个待探测点：地址、类型与只读取数器。"""

    address: str
    area: str
    kind: str
    reader: Callable[[], dict]

    def read(self) -> "Reading":
        """执行一次只读探测，读不到就把原因记下来。"""

        try:
            evidence = self.reader()
        except Exception as error:  # 读不到就是读不到，不能当成正常
            return Reading(self, None, f"{type(error).__name__}: {error}")
        return Reading(self, dict(evidence), None)


@dataclass(frozen=True)
class Reading:
    """一次探测的结果：要么拿到证据，要么记下失败原因。"""

    probe: Probe
    evidence: dict | None
    error: str | None

    @property
    def ok(self) -> bool:
        """是否拿到了证据。"""

        return self.error is None


def build_probe_plan(
    source: HeatSource,
    curve: HeatCurve,
    network: PrimaryNetwork,
    secondary: SecondaryLoop,
    pump: Pump,
    stations: dict[str, HeatStation],
    valves: dict[str, Valve],
    meters: QuotaAccumulator,
) -> list[Probe]:
    """按当前运行对象生成探测计划（实际侧清单），顺序固定。"""

    probes = [
        Probe("plant.heat_source", "plant", "heat-source", lambda: source.snapshot().as_dict()),
        Probe(
            "plant.weather",
            "plant",
            "weather-gateway",
            lambda: {"outdoor_c": round(curve.outdoor_c(), 2)},
        ),
        Probe("primary.supply_header", "primary", "header", lambda: network.snapshot().as_dict()),
        Probe(
            "primary.flow_meter",
            "primary",
            "flow-meter",
            lambda: {"flow_t_h": round(network.flow_t_h(), 2)},
        ),
        Probe("secondary.circulating_pump", "secondary", "pump", lambda: pump.snapshot().as_dict()),
        Probe(
            "secondary.makeup_valve",
            "secondary",
            "control-valve",
            lambda: {
                "pressure_kpa": round(secondary.pressure_kpa(), 2),
                "needs_makeup": secondary.needs_makeup(),
            },
        ),
        Probe(
            "secondary.pressure_sensor",
            "secondary",
            "pressure-sensor",
            lambda: {"pressure_kpa": round(secondary.pressure_kpa(), 2)},
        ),
    ]
    for name in sorted(stations):
        probes.append(
            Probe(
                f"station.{name}",
                "station",
                "heat-exchange-station",
                lambda name=name: stations[name].snapshot().as_dict(),
            )
        )
    for name in sorted(valves):
        probes.append(
            Probe(
                f"valve.{name}.mix",
                "valve",
                "mix-valve",
                lambda name=name: valves[name].snapshot().as_dict(),
            )
        )
    for meter in meters.meters():
        probes.append(
            Probe(
                f"quota.{meter}",
                "quota",
                "heat-meter",
                lambda meter=meter: meters.get(meter).snapshot().as_dict(),
            )
        )
    order = {area: index for index, area in enumerate(PROBE_ORDER)}
    return sorted(probes, key=lambda probe: (order[probe.area], probe.address))
