"""Render gate checklists from the stage machine.

Generated, not hand-written: the checklists cannot drift from stages.py.
"""

from __future__ import annotations

from pathlib import Path

from ccfa.stages import gate_for, stages_for

HEADER = """\
# {title}模式 gate 清单

本文件由 `tools/newpaper/checklists.py` 从 `tools/ccfa/stages.py` 生成。
不要手工编辑；改状态机后重新生成。

"""


def render_checklist(mode: str) -> str:
    stages = stages_for(mode)
    title = "会议" if mode == "conference" else "期刊"
    lines = [HEADER.format(title=title)]
    for index, stage in enumerate(stages, start=1):
        gate = gate_for(mode, stage)
        lines.append(f"## {index}. [{stage}]\n")
        lines.append(f"- [ ] gate `{gate.id}`")
        lines.append(f"  - 通过条件：{gate.criterion}\n")
    return "\n".join(lines)


def write_checklists(template_root: Path) -> list[Path]:
    written: list[Path] = []
    for mode, filename in (
        ("conference", "conference.md"),
        ("journal", "journal.md"),
    ):
        path = Path(template_root) / "checklists" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_checklist(mode), encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    for written_path in write_checklists(root):
        print(written_path)
