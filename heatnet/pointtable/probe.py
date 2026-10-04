"""现场侧探测。

点表是装机时登记的"声明侧"，这里维护的是"实际侧"：平台装配时按真实接线把每个
现场设备挂进清单，巡检时逐点读取证据。读点只取设备快照，不改任何状态；巡检
与控制在同一把锁下串行，读写不会互相打架。读不到的点记为证据缺失——设备可能
在也可能不在，既不能据此判正常，也不能据此判拆除。现场漂移（加站、改址、换型、
断通讯）通过 ``remove`` / ``set_kind`` / ``set_online`` 进入清单，点表登记不
会跟着自己变，两侧的不一致就是这样被巡检照出来的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class ProbeReading:
    """一个点的读取结果：要么拿到证据，要么拿到失败原因。"""

    address: str
    kind: str
    ok: bool
    evidence: dict = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "address": self.address,
            "kind": self.kind,
            "ok": self.ok,
            "evidence": dict(self.evidence),
            "error": self.error,
        }


class FieldPoint:
    """一个现场设备点：实际类型、读证据的回调与通讯状态。"""

    def __init__(self, area: str, device: str, kind: str, reader: Callable[[], dict]) -> None:
        if not area or not device or not kind:
            raise ValueError("区域、设备与类型都不能为空")
        self.area = area
        self.device = device
        self.kind = kind
        self._reader = reader
        self._online = True

    @property
    def address(self) -> str:
        return f"{self.area}.{self.device}"

    def set_online(self, online: bool) -> None:
        """置通讯状态；断通讯的点读不到证据。"""

        self._online = bool(online)

    def set_kind(self, kind: str) -> None:
        """现场换型后更新实际类型。"""

        if not kind:
            raise ValueError("类型不能为空")
        self.kind = str(kind)

    def read(self) -> ProbeReading:
        """读取一次现场证据；任何失败都记成读不到，绝不中断整轮巡检。"""

        if not self._online:
            return ProbeReading(self.address, self.kind, False, {}, "通讯中断")
        try:
            evidence = self._reader()
        except Exception as error:  # 单点读不到属于部分失败，不能拖垮整轮巡检
            return ProbeReading(self.address, self.kind, False, {}, str(error))
        return ProbeReading(self.address, self.kind, True, dict(evidence), "")


class FieldInventory:
    """现场实际设备清单，与点表登记互为声明／实际两侧。"""

    def __init__(self) -> None:
        self._points: dict[str, FieldPoint] = {}

    def add(self, point: FieldPoint) -> None:
        """挂入一个现场点（装配或现场加站时）。"""

        self._points[point.address] = point

    def remove(self, address: str) -> None:
        """摘掉一个现场点（设备拆除或改址后原地址不再存在）。"""

        self._points.pop(address, None)

    def get(self, address: str) -> FieldPoint:
        """按地址取现场点。"""

        return self._points[address]

    def set_online(self, address: str, online: bool) -> None:
        """置某个点的通讯状态。"""

        self._points[address].set_online(online)

    def set_kind(self, address: str, kind: str) -> None:
        """现场换型后更新某个点的实际类型。"""

        self._points[address].set_kind(kind)

    def probe(self, area_order: tuple[str, ...]) -> list[ProbeReading]:
        """按区域顺序逐点读取，同一区域内按地址排序，顺序定死可复现。"""

        rank = {area: index for index, area in enumerate(area_order)}
        ordered = sorted(
            self._points.values(),
            key=lambda point: (rank.get(point.area, len(rank)), point.address),
        )
        return [point.read() for point in ordered]
