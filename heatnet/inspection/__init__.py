"""点表巡检与核对。

现场点表（:class:`~heatnet.ns.registry.NamespaceRegistry`）是装机时登记的声明；
之后加站、改地址、换类型都会造成声明与实际漂移，等到启停时才发现对不上。本包
把声明和实际定期对一遍：

- :mod:`~heatnet.inspection.plan` 按调度链顺序生成探测计划，巡检全程只读；
- :mod:`~heatnet.inspection.reconcile` 逐点全量核对（不做抽样），列出多出来的、
  少掉的、类型写错的与读不到的；
- :mod:`~heatnet.inspection.policy` 按设备类型定死"拦住相关动作还是只记审计"，
  并给出可执行的处置建议；
- :mod:`~heatnet.inspection.patrol` 执行巡检、维护闸门、落审计并执行处置。
"""

from .patrol import Inspector
from .plan import PROBE_ORDER, build_probe_plan
from .policy import DEFAULT_POLICY
from .reconcile import STRATEGY, reconcile

__all__ = [
    "DEFAULT_POLICY",
    "PROBE_ORDER",
    "STRATEGY",
    "Inspector",
    "build_probe_plan",
    "reconcile",
]
