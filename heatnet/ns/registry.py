"""现场命名空间注册表。

现场地址统一写成 ``<area>.<device>``，注册时带上设备类型。重复注册、解析未注册
地址都会抛出 :class:`NamespaceError`——控制台和审计共享同一套名字，任何一边拼错
地址都必须当场暴露，不能静默降级。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import NamespaceError


@dataclass(frozen=True)
class Device:
    """一个已登记的现场设备。"""

    area: str
    device: str
    kind: str

    @property
    def address(self) -> str:
        return f"{self.area}.{self.device}"

    def as_dict(self) -> dict:
        return {"area": self.area, "device": self.device, "kind": self.kind, "address": self.address}


class NamespaceRegistry:
    """区域／设备命名空间注册表。"""

    def __init__(self, unit: str = "heatnet") -> None:
        self._unit = unit
        self._devices: dict[str, Device] = {}

    @property
    def unit(self) -> str:
        return self._unit

    def register(self, area: str, device: str, kind: str) -> Device:
        """登记一个设备，地址重复即报错。"""

        if not area or not device or not kind:
            raise NamespaceError("区域、设备与类型都不能为空", component="ns")
        address = f"{area}.{device}"
        if address in self._devices:
            raise NamespaceError(f"地址已注册: {address}", component="ns")
        entry = Device(area, device, kind)
        self._devices[address] = entry
        return entry

    def deregister(self, address: str) -> Device:
        """从点表注销一个地址（巡检确认现场已拆除后执行）。"""

        try:
            return self._devices.pop(address)
        except KeyError as error:
            raise NamespaceError(f"未注册地址: {address}", component="ns") from error

    def correct_kind(self, address: str, kind: str) -> Device:
        """按现场实际类型更正点表登记。"""

        if not kind:
            raise NamespaceError("类型不能为空", component="ns")
        try:
            entry = self._devices[address]
        except KeyError as error:
            raise NamespaceError(f"未注册地址: {address}", component="ns") from error
        corrected = Device(entry.area, entry.device, str(kind))
        self._devices[address] = corrected
        return corrected

    def table(self) -> dict[str, str]:
        """返回点表（地址 → 类型，按地址排序），供巡检逐点核对。"""

        return {address: self._devices[address].kind for address in sorted(self._devices)}

    def resolve(self, address: str) -> Device:
        """按地址解析设备。"""

        try:
            return self._devices[address]
        except KeyError as error:
            raise NamespaceError(f"未注册地址: {address}", component="ns") from error

    def addresses(self) -> list[str]:
        """返回全部地址（排序后）。"""

        return sorted(self._devices)

    def by_kind(self, kind: str) -> list[Device]:
        """按设备类型筛选。"""

        return [entry for entry in self._devices.values() if entry.kind == kind]

    def kinds(self) -> list[str]:
        """返回已登记的设备类型（排序后）。"""

        return sorted({entry.kind for entry in self._devices.values()})

    def describe(self) -> dict:
        """汇总命名空间，供状态快照读取。"""

        areas: dict[str, list[dict]] = {}
        for entry in self._devices.values():
            areas.setdefault(entry.area, []).append(entry.as_dict())
        return {
            "unit": self._unit,
            "count": len(self._devices),
            "addresses": self.addresses(),
            "areas": areas,
        }
