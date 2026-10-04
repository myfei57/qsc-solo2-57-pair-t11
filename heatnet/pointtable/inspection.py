"""点表巡检编排。

一轮巡检只做三件事：按定死的顺序把现场逐点读一遍、把声明与实际逐点比对、
按设备类型给每条发现定处置。判定规则：

- 全部点对上且证据齐全 → ``ok``；
- 有点读不到但没有硬性不一致 → ``partial``（部分失败，不能判正常）；
- 存在少登、多挂或类型写错 → ``mismatch``。

巡检本身只读不写，并复用平台同一把锁，读写不会互相打架；报告既给控制台展示，
也落审计流水并落盘，跨重启恢复后与点表仍是同一份地址口径。
"""

from __future__ import annotations

from .diff import EXTRA, MISSING, TYPE_MISMATCH, UNVERIFIED, diff_points
from .policy import AREAS, BLOCK, METHOD, blocked_operations
from .probe import FieldInventory

OK = "ok"
PARTIAL = "partial"
MISMATCH = "mismatch"


def run_inspection(declared: dict[str, str], inventory: FieldInventory, *, now: float, origin: str) -> dict:
    """跑一轮点表巡检，返回完整报告（供控制台展示与落审计）。"""

    readings = inventory.probe(AREAS)
    findings = diff_points(declared, readings)
    finding_dicts = [finding.as_dict() for finding in findings]
    hard = [finding for finding in findings if finding.cls in (MISSING, EXTRA, TYPE_MISMATCH)]
    unverified = [finding for finding in findings if finding.cls == UNVERIFIED]
    if hard:
        verdict = MISMATCH
    elif unverified:
        verdict = PARTIAL
    else:
        verdict = OK
    counts = {cls: 0 for cls in (MISSING, EXTRA, TYPE_MISMATCH, UNVERIFIED)}
    for finding in findings:
        counts[finding.cls] += 1
    return {
        "ok": verdict == OK,
        "verdict": verdict,
        "origin": origin,
        "ts": round(float(now), 3),
        "method": METHOD,
        "order": list(AREAS),
        "totals": {
            "declared": len(declared),
            "actual": len(readings),
            "probed": sum(1 for reading in readings if reading.ok),
            "findings": len(findings),
            **counts,
        },
        "findings": finding_dicts,
        "blocked_operations": blocked_operations(finding_dicts),
        "readings": [reading.as_dict() for reading in readings],
    }


def severity_of(report: dict) -> str:
    """巡检汇总事件用的严重度：正常 notice；带拦截档发现 alarm；其余 warning。"""

    if report["verdict"] == OK:
        return "notice"
    if any(finding["policy"] == BLOCK for finding in report["findings"]):
        return "alarm"
    return "warning"
