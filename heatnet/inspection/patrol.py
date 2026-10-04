"""巡检执行与闸门。

:class:`Inspector` 持有声明侧（命名空间注册表）与实际侧（探测计划供应商）。每次
巡检：快照声明点表 → 按固定顺序只读探测 → 逐点核对 → 汇总报告 → 落审计。巡检
全程持有平台执行器锁（与控制周期同一把），读写不会互相打架；报告、审计事件与
控制台展示出自同一个报告对象，``run_id`` 把三者串成同一次巡检，点表快照随报告
存档，事后改点表改不动历史结论。

闸门按设备类型策略判定：存在 ``block`` 策略的未处置发现时闸门关闭，投运与调度
不得下发；``record`` 策略的发现只记告警。还没有任何一次巡检结论时闸门同样视为
关闭——没有证据不能当成正常。停运是安全方向，永远不受闸门限制。
"""

from __future__ import annotations

import threading
from typing import Callable, Mapping

from ..clock import Clock
from ..errors import PlantError
from ..eventbus import Event, EventBus
from ..ids import IdFactory
from ..ns.registry import NamespaceRegistry
from .plan import PROBE_ORDER, Probe
from .policy import BLOCK, DEFAULT_POLICY, RECORD
from .reconcile import STRATEGY, reconcile


class Inspector:
    """点表巡检器：执行巡检、维护闸门、执行处置。"""

    def __init__(
        self,
        namespaces: NamespaceRegistry,
        plan_supplier: Callable[[], list[Probe]],
        clock: Clock,
        bus: EventBus,
        ids: IdFactory,
        lock: threading.RLock,
        policy: Mapping[str, str] | None = None,
    ) -> None:
        self._namespaces = namespaces
        self._plan_supplier = plan_supplier
        self._clock = clock
        self._bus = bus
        self._ids = ids
        self._lock = lock
        self._policy = dict(DEFAULT_POLICY if policy is None else policy)
        self._last: dict | None = None
        self._runs = 0

    def run(self, trigger: str = "manual") -> dict:
        """执行一次巡检，返回报告；报告同时落审计。"""

        with self._lock:
            declared = self._namespaces.snapshot()
            readings = [probe.read() for probe in self._plan_supplier()]
            result = reconcile(declared, readings, self._policy)
            report = {
                "run_id": self._ids.next(),
                "ts": round(self._clock.now(), 3),
                "trigger": trigger,
                "strategy": result["strategy"],
                "declared": {"count": len(declared), "snapshot": dict(sorted(declared.items()))},
                "actual": {"count": len(readings)},
                "evidence": result["evidence"],
                "ok": result["ok"],
                "counts": result["counts"],
                "points": result["points"],
                "findings": result["findings"],
            }
            self._last = report
            self._runs += 1
            self._publish(report)
            return report

    def _publish(self, report: dict) -> None:
        """把本次巡检的每条发现与汇总写进事件总线（审计随之落盘）。"""

        for finding in report["findings"]:
            self._bus.publish(
                Event.of(
                    "inspection",
                    "inspection",
                    "drift",
                    severity="alarm" if finding["policy"] == BLOCK else "warning",
                    message=f"{finding['address']}：{finding['detail']}",
                    asset=finding["address"],
                    run_id=report["run_id"],
                    category=finding["category"],
                    declared_kind=finding["declared_kind"],
                    actual_kind=finding["actual_kind"],
                    policy=finding["policy"],
                    disposition=finding["recommendation"]["action"],
                )
            )
        blocks = [item for item in report["findings"] if item["policy"] == BLOCK]
        severity = "notice" if report["ok"] else ("alarm" if blocks else "warning")
        message = (
            f"巡检 {report['run_id']} 通过"
            if report["ok"]
            else f"巡检 {report['run_id']} 发现 {len(report['findings'])} 处不一致"
        )
        self._bus.publish(
            Event.of(
                "inspection",
                "inspection",
                "patrol",
                severity=severity,
                message=message,
                run_id=report["run_id"],
                trigger=report["trigger"],
                strategy=report["strategy"],
                ok=report["ok"],
                evidence=report["evidence"],
                findings=len(report["findings"]),
                blocks=len(blocks),
            )
        )

    def latest(self) -> dict | None:
        """返回最近一次巡检报告，还没有巡检过时返回 ``None``。"""

        with self._lock:
            return self._last

    def gate(self) -> dict:
        """返回闸门状态：存在 block 档未处置发现（或毫无证据）时闸门关闭。"""

        with self._lock:
            if self._last is None:
                return {
                    "open": False,
                    "reason": "no-evidence",
                    "run_id": None,
                    "blocks": [],
                    "records": [],
                }
            blocks = [
                item["address"] for item in self._last["findings"] if item["policy"] == BLOCK
            ]
            records = [
                item["address"] for item in self._last["findings"] if item["policy"] == RECORD
            ]
            return {
                "open": not blocks,
                "run_id": self._last["run_id"],
                "blocks": blocks,
                "records": records,
            }

    def summary(self) -> dict:
        """返回巡检紧凑摘要，供平台状态快照读取。"""

        with self._lock:
            latest = None
            if self._last is not None:
                latest = {
                    key: self._last[key]
                    for key in ("run_id", "ts", "trigger", "ok", "evidence", "counts")
                }
            return {"runs": self._runs, "gate": self.gate(), "latest": latest}

    def describe(self) -> dict:
        """返回巡检策略、顺序、闸门与最近一次完整报告，供控制台展示。"""

        with self._lock:
            return {
                "strategy": STRATEGY,
                "probe_order": list(PROBE_ORDER),
                "policy": dict(self._policy),
                "runs": self._runs,
                "gate": self.gate(),
                "report": self._last,
            }

    def apply(self, address: str) -> dict:
        """按最近一次巡检的处置建议更正点表，并立即复巡。"""

        with self._lock:
            if not address:
                raise PlantError("处置地址不能为空", component="inspection")
            if self._last is None:
                raise PlantError("还没有巡检结论，先跑一遍巡检再处置", component="inspection")
            finding = next(
                (item for item in self._last["findings"] if item["address"] == address), None
            )
            if finding is None:
                raise PlantError(
                    f"最近一次巡检没有该地址的待处置发现: {address}", component="inspection"
                )
            action = finding["recommendation"]["action"]
            if action == "deregister":
                self._namespaces.deregister(address)
            elif action == "register":
                area, device = address.split(".", 1)
                self._namespaces.register(area, device, str(finding["actual_kind"]))
            elif action == "correct-kind":
                self._namespaces.correct_kind(address, str(finding["actual_kind"]))
            # re-probe 不改点表，只复巡。
            self._bus.publish(
                Event.of(
                    "inspection",
                    "inspection",
                    "disposition",
                    severity="notice",
                    message=f"处置 {address}：{action}",
                    asset=address,
                    run_id=self._last["run_id"],
                    category=finding["category"],
                    action_taken=action,
                )
            )
            report = self.run("disposition")
            return {
                "applied": {
                    "address": address,
                    "action": action,
                    "category": finding["category"],
                },
                "report": report,
            }
