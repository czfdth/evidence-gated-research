"""Stage and gate definitions: the single source of truth.

Design doc section 4.1/4.2. Checklists and ccfa.yaml validation both read
from here so the documentation cannot drift from the state machine.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import NamedTuple


class Gate(NamedTuple):
    id: str
    criterion: str


SHARED_STAGES: list[str] = [
    "idea",
    "grounded",
    "data-ready",
    "experiment-design",
    "experiments-running",
    "results-ready",
    "writing",
    "internal-review",
    "submission-check",
    "submitted",
]

CONFERENCE_TAIL: list[str] = ["rebuttal", "camera-ready", "archived"]
JOURNAL_TAIL: list[str] = [
    "major-revision",
    "response-letter",
    "resubmitted",
    "accepted",
    "archived",
]

_SHARED_GATES: dict[str, Gate] = {
    "idea": Gate(
        "scope_defined",
        "问题陈述、至少一条可检验假设、目标 venue 均写明",
    ),
    "grounded": Gate(
        "novelty_grounded",
        "列出三篇最近邻工作及各自盲区，说明本工作填补的是哪一个无人测量的合取；"
        "novelty-audit 记录检索范围/日期与逐 claim 差异；禁止没人做过式表述",
    ),
    "data-ready": Gate(
        "provenance_recorded",
        "逐份数据有来源、分类与校验和；来源文档可被脚本核对；不合规来源已排除",
    ),
    "experiment-design": Gate(
        "design_frozen",
        "每个 claim 对应一个实验；baseline 来源明确；metric 定义明确；"
        "statistics-plan 含 alpha/多重比较、功效与样本量、种子、停止规则、"
        "缺失数据处理与平台画像",
    ),
    "experiments-running": Gate(
        "results_recorded",
        "experiments/log/ 逐次运行留有配置、种子、commit、退出码、指标",
    ),
    "results-ready": Gate(
        "claims_supported",
        "每个 claim 指到具体数值，且该数值通过行内标记脚本核对；"
        "无支撑项标记待验证或删除",
    ),
    "writing": Gate(
        "draft_complete",
        "正文、图表、引用齐备；页数符合 venue；所有引用条目来自检索期已核验的条目",
    ),
    "internal-review": Gate(
        "review_cleared",
        "跨模型评审报告无 blocking 项；引用、数字、图表三项核验通过；"
        "人工证明复核、引用语义支持与图表语义支持台账无未复核项",
    ),
    "submission-check": Gate(
        "package_ready",
        "模板、匿名、页数、元数据检查通过；复现包在干净环境实际重跑成功；"
        "repro-environment 记录 lockfile 哈希与系统工具版本证据；"
        "governance 台账齐备（署名/贡献、COI、伦理与许可、AI 使用、查重、"
        "双用途与负责任披露）",
    ),
    "submitted": Gate("venue_decided", "收到 venue 决定，评审意见归档"),
}

_CONFERENCE_GATES: dict[str, Gate] = {
    "rebuttal": Gate("rebuttal_submitted", "逐条回应完成，修改范围与承诺一致"),
    "camera-ready": Gate(
        "final_package_ready", "终稿符合 camera-ready 规范；确定性终稿检查通过"
    ),
    "archived": Gate("archived", "终稿、复现包、数据来源文档归档"),
}

_JOURNAL_GATES: dict[str, Gate] = {
    "major-revision": Gate(
        "revision_planned", "每条意见有明确处置方案，含不采纳的正当理由"
    ),
    "response-letter": Gate("response_complete", "逐点回复完成，与实际改动一致"),
    "resubmitted": Gate("resubmission_ready", "改动稿与回复信齐备，修改痕迹保留"),
    "accepted": Gate("accepted", "数据来源文档、model card、data card 齐备"),
    "archived": Gate("archived", "确定性终稿检查通过；全部材料归档"),
}


def stages_for(mode: str) -> list[str]:
    if mode == "conference":
        return SHARED_STAGES + CONFERENCE_TAIL
    if mode == "journal":
        return SHARED_STAGES + JOURNAL_TAIL
    raise ValueError(f"未知 mode: {mode!r}，应为 conference 或 journal")


def gate_for(mode: str, stage: str) -> Gate:
    stages_for(mode)
    if stage in _SHARED_GATES:
        return _SHARED_GATES[stage]
    table = _CONFERENCE_GATES if mode == "conference" else _JOURNAL_GATES
    return table[stage]


def all_gates(mode: str) -> list[tuple[str, Gate]]:
    return [(stage, gate_for(mode, stage)) for stage in stages_for(mode)]


def _gate_payload(gate: Gate) -> dict:
    return {"id": gate.id, "criterion": gate.criterion}


def main(argv: list[str] | None = None) -> int:
    """Print the stage/gate table as JSON.

    This exists so external consumers (the desktop workbench) can read the
    state machine without importing ``ccfa`` into their own process. The table
    stays owned here; nothing downstream reimplements it.
    """
    parser = argparse.ArgumentParser(
        description="输出 stage/gate 表（JSON 到 stdout）"
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("conference", "journal"),
        help="论文模式",
    )
    parser.add_argument(
        "--stage",
        help="只输出该 stage 的 gate",
    )
    args = parser.parse_args(argv)

    try:
        stages = stages_for(args.mode)
        gates = {stage: _gate_payload(gate_for(args.mode, stage)) for stage in stages}
    except ValueError as exc:
        print(f"工具错误: {exc}", file=sys.stderr)
        return 2

    if args.stage is not None:
        if args.stage not in gates:
            print(f"工具错误: 未知 stage: {args.stage!r}", file=sys.stderr)
            return 2
        payload = {
            "mode": args.mode,
            "stage": args.stage,
            "gate": gates[args.stage],
        }
    else:
        payload = {"mode": args.mode, "stages": stages, "gates": gates}
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
