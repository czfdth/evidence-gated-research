"""Generate Figma-importable SVG mockups for the paper workbench.

Design tokens are loaded straight out of ``app/ccfa_gui/theme.py`` (by file, so
no Qt import is needed), which means the mockups cannot drift from the shipped
stylesheet. Run:

    python docs/design/generate_mockups.py                 # light -> exports/
    CCFA_MOCKUP_MODE=dark python docs/design/generate_mockups.py   # -> exports/dark/

Figma import: drag the SVG onto the canvas. Text stays editable and every
``<g id=...>`` becomes a named layer.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "exports"


def _load_theme():
    path = REPO_ROOT / "app" / "ccfa_gui" / "theme.py"
    spec = importlib.util.spec_from_file_location("ccfa_theme_tokens", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_icon_paths():
    path = REPO_ROOT / "app" / "ccfa_gui" / "icon_paths.py"
    spec = importlib.util.spec_from_file_location("ccfa_icon_paths", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


T = _load_theme()
ICONS = _load_icon_paths()

# Light and dark exports come from the same source: pick the palette up front,
# so every default argument and literal below binds to the chosen mode.
MODE = os.environ.get("CCFA_MOCKUP_MODE", "light").strip().casefold()
MODE = "dark" if MODE == "dark" else "light"
PALETTE = T.palette(MODE)

ACCENT = PALETTE["accent"]
ACCENT_HOVER = PALETTE["accent_hover"]
INK = PALETTE["ink"]
MUTED = PALETTE["muted"]
LINE = PALETTE["line"]
CANVAS = PALETTE["canvas"]
PANEL = PALETTE["panel"]
PROBLEM = PALETTE["problem"]
ADVISORY = PALETTE["advisory"]
OK = PALETTE["ok"]
CHIP = PALETTE["chip"]
SELECTED = PALETTE["row_selected"]
FIELD_BORDER = PALETTE["field_border"]
TABLE_HEADER = PALETTE["table_header"]
GRIDLINE = PALETTE["gridline"]
PLACEHOLDER_ICON = PALETTE["placeholder_icon"]
ERROR_BG = PALETTE["badge_problem_bg"]
ERROR_BORDER = PALETTE["badge_problem_border"]
PENDING_BG = PALETTE["banner_pending_bg"]
PENDING_BORDER = PALETTE["banner_pending_border"]
MONO = "'JetBrains Mono', Consolas, 'Cascadia Mono', monospace"
SANS = "'Inter', 'Segoe UI', 'Microsoft YaHei UI', sans-serif"

# Chat bubble roles: role label, fill, border, label colour.
BUBBLES = {
    "user": {"label": "你", "fill": SELECTED, "border": LINE, "text": ACCENT},
    "assistant": {"label": "助手", "fill": PANEL, "border": LINE, "text": MUTED},
    "tool": {"label": "read_file  [read]", "fill": CHIP, "border": LINE, "text": OK},
    "tool-denied": {
        "label": "write_file  [write]",
        "fill": CHIP,
        "border": LINE,
        "text": PROBLEM,
    },
    "error": {
        "label": "错误",
        "fill": ERROR_BG,
        "border": ERROR_BORDER,
        "text": PROBLEM,
    },
    "stopped": {
        "label": "已停止",
        "fill": PENDING_BG,
        "border": PENDING_BORDER,
        "text": ADVISORY,
    },
}

W, H = 1280, 800
TOOLBAR_H = 40
STATUS_H = 24
MARGIN = 8
SIDEBAR_W = 220
CHAT_W = 420
DETAIL_X = MARGIN + SIDEBAR_W + MARGIN
DETAIL_W = W - DETAIL_X - CHAT_W - MARGIN * 2
CHAT_X = W - CHAT_W - MARGIN
BODY_Y = TOOLBAR_H + MARGIN
BODY_H = H - BODY_Y - STATUS_H - MARGIN


def esc(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def clip(value: str, limit: int) -> str:
    """Trim a label so it cannot run past its card in the mockup."""

    text = str(value)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class Svg:
    def __init__(self, width: int, height: int, background: str = CANVAS):
        self.width = width
        self.height = height
        self.parts: list[str] = [
            f'<rect x="0" y="0" width="{width}" height="{height}" fill="{background}"/>'
        ]

    def layer(self, name: str, *parts: str) -> None:
        # One element per line keeps the generated files reviewable in git.
        body = "\n    ".join(part for part in parts if part)
        self.parts.append(f'<g id="{esc(name)}">\n    {body}\n  </g>')

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: str = "none",
        stroke: str | None = None,
        r: float = 0,
        sw: float = 1,
    ) -> str:
        stroke_attr = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
        return (
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
            f'fill="{fill}"{stroke_attr}/>'
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, stroke: str = LINE) -> str:
        return (
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{stroke}" stroke-width="1"/>'
        )

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        size: float = 12,
        fill: str = INK,
        weight: int = 400,
        anchor: str = "start",
        family: str = SANS,
    ) -> str:
        return (
            f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">'
            f"{esc(value)}</text>"
        )

    def icon(
        self,
        name: str,
        x: float,
        y: float,
        *,
        size: float = 16,
        colour: str = INK,
    ) -> str:
        """Draw one of the app's vector icons at (x, y)."""

        body = "".join(ICONS.ICONS[name])
        scale = size / 24
        return (
            f'<g transform="translate({x},{y}) scale({scale})" fill="none" '
            f'stroke="{colour}" stroke-width="1.75" stroke-linecap="round" '
            f'stroke-linejoin="round">{body}</g>'
        )

    def mark(self, x: float, y: float, *, size: float = 22) -> str:
        """Draw the product mark: accent rounded square with three bars."""

        bars = "".join(
            f'<path d="M7 {8 + index * 4}h{width}" fill="none" stroke="#ffffff" '
            f'stroke-width="1.8" stroke-linecap="round"/>'
            for index, width in enumerate((10, 10, 6))
        )
        return "".join(
            [
                self.rect(x, y, size, size, fill=ACCENT, r=size * 6 / 24),
                f'<g transform="translate({x},{y}) scale({size / 24})">{bars}</g>',
            ]
        )

    def render(self) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
            f'height="{self.height}" viewBox="0 0 {self.width} {self.height}">'
            + "\n  "
            + "\n  ".join(self.parts)
            + "\n"
            + "</svg>"
            + "\n"
        )


def button(
    svg: Svg,
    x: float,
    y: float,
    w: float,
    label: str,
    *,
    primary: bool = False,
    h: float = 28,
    icon_name: str | None = None,
) -> str:
    fill = ACCENT if primary else PANEL
    stroke = ACCENT if primary else FIELD_BORDER
    colour = "#ffffff" if primary else INK
    parts = [svg.rect(x, y, w, h, fill=fill, stroke=stroke, r=6)]
    if icon_name:
        parts.append(
            svg.icon(
                icon_name,
                x + 9,
                y + (h - 16) / 2,
                size=16,
                colour=colour,
            )
        )
    parts.append(
        svg.text(
            # Centre the label in the space left of the icon, not in the whole
            # button, otherwise a narrow button collides with its own icon.
            x + (w + (25 if icon_name else 0)) / 2,
            y + h / 2 + 4,
            label,
            size=12,
            fill=colour,
            weight=600 if primary else 400,
            anchor="middle",
        )
    )
    return "".join(parts)


def chip(svg: Svg, x: float, y: float, label: str, *, fill: str = CHIP,
         colour: str = INK) -> str:
    width = 12 + len(label) * 7.2 + 6
    return "".join(
        [
            svg.rect(x, y, width, 20, fill=fill, stroke=LINE, r=4),
            svg.text(x + width / 2, y + 14, label, size=11, fill=colour, anchor="middle"),
        ]
    )


def toolbar(svg: Svg, summary: str) -> None:
    parts = [
        svg.rect(0, 0, svg.width, TOOLBAR_H, fill=PANEL),
        svg.line(0, TOOLBAR_H, svg.width, TOOLBAR_H),
        svg.mark(10, 9),
        svg.text(40, 25, "论文工作台", size=12, weight=600),
        button(svg, 122, 6, 80, "刷新", icon_name="refresh"),
        button(svg, 210, 6, 74, "设置", icon_name="settings"),
        button(svg, 292, 6, 36, "", icon_name="chat"),
        svg.text(svg.width - 12, 24, summary, size=12, fill=MUTED, anchor="end"),
    ]
    svg.layer("toolbar", *parts)


def status_bar(svg: Svg, workflow: str, credential: str) -> None:
    y = H - STATUS_H
    svg.layer(
        "status-bar",
        svg.rect(0, y, svg.width, STATUS_H, fill=PANEL),
        svg.line(0, y, svg.width, y),
        svg.text(12, y + 16, workflow, size=11, fill=MUTED),
        svg.text(svg.width - 12, y + 16, credential, size=11, fill=OK, anchor="end"),
    )


def project_list(
    svg: Svg,
    items: list[tuple[str, str | None]],
    selected: int,
) -> None:
    x, y, w = MARGIN, BODY_Y, SIDEBAR_W
    h = svg.height - BODY_Y - STATUS_H - MARGIN
    parts = [
        svg.rect(x, y, w, h, fill=PANEL, stroke=LINE, r=6),
        svg.text(x + 12, y + 24, "项目", size=11, fill=MUTED, weight=600),
    ]
    row_y = y + 34
    for index, (label, error) in enumerate(items):
        row = svg.rect(x + 8, row_y, w - 16, 28, fill=SELECTED if index == selected else "none", r=4)
        colour = PROBLEM if error else INK
        marker = "▲" if error else "●"
        text = svg.text(x + 16, row_y + 19, f"{marker} {label}", size=12, fill=colour)
        parts.extend([row, text])
        if error:
            parts.append(
                svg.text(x + 30, row_y + 38, error, size=11, fill=PROBLEM)
            )
            row_y += 44
        else:
            row_y += 32
    svg.layer("project-list", *parts)


def chat_panel(svg: Svg, configured: bool, messages: list[tuple[str, str]] | None = None) -> None:
    x, y, w = CHAT_X, BODY_Y, CHAT_W
    h = svg.height - BODY_Y - STATUS_H - MARGIN
    parts = [
        svg.rect(x, y, w, h, fill=PANEL, stroke=LINE, r=6),
        svg.text(x + 12, y + 24, "对话", size=11, fill=MUTED, weight=600),
        svg.text(x + 12, y + 56, "引擎", size=12),
        svg.rect(x + w - 178, y + 40, 166, 28, fill=PANEL, stroke=FIELD_BORDER, r=6),
        svg.text(x + w - 166, y + 58, "OpenAI 兼容", size=12),
    ]
    box_y = y + 80
    box_h = h - 300
    parts.append(svg.rect(x + 12, box_y, w - 24, box_h, fill=PANEL, stroke=LINE, r=6))
    if messages:
        bubble_y = box_y + 10
        for role, body in messages:
            lines = body.split("\n")
            bubble_h = 40 + 18 * len(lines)
            parts.append(
                svg.rect(
                    x + 22,
                    bubble_y,
                    w - 44,
                    bubble_h,
                    fill=BUBBLES[role]["fill"],
                    stroke=BUBBLES[role]["border"],
                    r=6,
                )
            )
            parts.append(
                svg.text(
                    x + 34,
                    bubble_y + 22,
                    BUBBLES[role]["label"],
                    size=11,
                    fill=BUBBLES[role]["text"],
                    weight=600,
                )
            )
            for index, line in enumerate(lines):
                # A leading ">" marks a code line: monospace, like the app.
                code = line.startswith(">")
                parts.append(
                    svg.text(
                        x + 34,
                        bubble_y + 38 + index * 18,
                        clip(line.lstrip(">"), 40 if code else 34),
                        size=12,
                        fill=INK,
                        family=MONO if code else SANS,
                    )
                )
            bubble_y += bubble_h + 8
    parts.extend(
        [
            svg.text(
                x + 12,
                box_y + box_h + 24,
                "未配置 provider：请先在设置中填写 API 配置"
                if not configured
                else "已连接 deepseek-v4-flash",
                size=12,
                fill=MUTED,
            ),
            svg.rect(x + 12, box_y + box_h + 34, w - 24, 96, fill=PANEL, stroke=FIELD_BORDER, r=6),
            svg.text(
                x + 24,
                box_y + box_h + 58,
                "输入消息，Ctrl+Enter 发送",
                size=12,
                fill=MUTED,
            ),
            button(svg, x + 12, y + h - 42, 74, "发送", h=28, icon_name="send"),
        ]
    )
    svg.layer("chat-panel", *parts)


def detail_header(
    svg: Svg,
    slug: str,
    note: str,
    badges: list[tuple[str, bool]],
    *,
    broken: bool = False,
    x: float = DETAIL_X,
    w: float = DETAIL_W,
) -> None:
    y, h = BODY_Y, 96
    parts = [
        svg.rect(x, y, w, h, fill=PANEL, stroke=LINE, r=6),
        svg.text(x + 14, y + 32, slug, size=17, fill=INK, weight=600),
        svg.text(x + 14, y + 54, note, size=12, fill=MUTED),
        svg.rect(x + w - 40, y + 12, 26, 26, fill=PANEL, stroke=FIELD_BORDER, r=6),
        svg.icon("folder", x + w - 35, y + 17, size=16, colour=MUTED),
    ]
    chip_x = x + 14
    for index, (label, is_problem) in enumerate(badges):
        if index == 2 and broken:
            parts.append(chip(svg, chip_x, y + 64, label))
        elif is_problem:
            parts.append(chip(svg, chip_x, y + 64, label, fill=ERROR_BG, colour=PROBLEM))
        else:
            parts.append(chip(svg, chip_x, y + 64, label))
        chip_x += 12 + len(label) * 7.2 + 18
    svg.layer("detail-header", *parts)


def action_row(
    svg: Svg,
    summary: str,
    summary_colour: str,
    *,
    x: float = DETAIL_X,
    w: float = DETAIL_W,
) -> None:
    y = BODY_Y + 104
    parts = [
        button(
            svg,
            x,
            y,
            118,
            "运行 validate",
            primary=True,
            icon_name="validate",
        ),
        button(
            svg,
            x + 126,
            y,
            138,
            "运行 milestones",
            icon_name="milestones",
        ),
        svg.text(
            x + w - 4,
            y + 19,
            summary,
            size=12,
            fill=summary_colour,
            anchor="end",
        ),
    ]
    svg.layer("action-row", *parts)


def results_table(
    svg: Svg,
    rows: list[tuple[str, str, str]],
    *,
    height: int = 526,
    x: float = DETAIL_X,
    w: float = DETAIL_W,
) -> None:
    y = BODY_Y + 140
    parts = [
        svg.rect(x, y, w, height, fill=PANEL, stroke=LINE, r=6),
        svg.rect(x + 1, y + 1, w - 2, 28, fill=TABLE_HEADER, r=5),
        svg.line(x + 1, y + 29, x + w - 1, y + 29),
        svg.text(x + 14, y + 20, "来源", size=11, fill=MUTED, weight=600),
        svg.text(x + 90, y + 20, "代码", size=11, fill=MUTED, weight=600),
        svg.text(x + 190, y + 20, "消息", size=11, fill=MUTED, weight=600),
    ]
    row_y = y + 30
    for source, code, message in rows:
        parts.append(svg.text(x + 14, row_y + 18, source, size=12))
        colour = T.severity_color(code, MODE)
        parts.append(
            svg.text(x + 90, row_y + 18, code, size=11, fill=colour, family=MONO, weight=600)
        )
        parts.append(svg.text(x + 190, row_y + 18, clip(message, 62), size=12, fill=INK))
        parts.append(svg.line(x + 1, row_y + 28, x + w - 1, row_y + 28, stroke=GRIDLINE))
        row_y += 28
    svg.layer("results-table", *parts)


def checkpoint_panel(
    svg: Svg,
    items: list[tuple[str, str, str, str]],
    *,
    banner: str,
    x: float = DETAIL_X,
    w: float = DETAIL_W,
    y: float = BODY_Y,
) -> None:
    """The proposed "待人工决定" surface, fed by readiness.human_review.checkpoints."""

    parts = [
        svg.rect(x, y, w, 72, fill=PENDING_BG, stroke=PENDING_BORDER, r=6),
        svg.text(x + 14, y + 28, banner, size=13, fill=ADVISORY, weight=600),
        svg.text(
            x + 14,
            y + 50,
            "脚本只能证明它还没被回答，不能替你回答。",
            size=12,
            fill=MUTED,
        ),
    ]
    card_y = y + 84
    for kind, question, ledger, hint in items:
        card_h = 100
        parts.extend(
            [
                svg.rect(x, card_y, w, card_h, fill=PANEL, stroke=LINE, r=6),
                chip(
                    svg,
                    x + 14,
                    card_y + 14,
                    "approve" if kind == "approve" else "feedback",
                    fill=CHIP if kind == "approve" else PENDING_BG,
                    colour=INK if kind == "approve" else ADVISORY,
                ),
                button(svg, x + w - 104, card_y + 12, 90, "打开台账", h=26),
                svg.text(x + 14, card_y + 54, clip(question, 42), size=13),
                svg.text(
                    x + 14,
                    card_y + 78,
                    clip(f"{ledger} — {hint}", 62),
                    size=11,
                    fill=MUTED,
                    family=MONO,
                ),
            ]
        )
        card_y += card_h + 8
    svg.layer("human-checkpoints", *parts)


def screen_empty() -> str:
    svg = Svg(W, H)
    toolbar(svg, "papers/ 下没有项目")
    project_list(svg, [], -1)
    center = DETAIL_X + DETAIL_W / 2
    svg.layer(
        "detail-empty",
        svg.rect(DETAIL_X, BODY_Y, DETAIL_W, 96, fill=PANEL, stroke=LINE, r=6),
        svg.text(DETAIL_X + 14, BODY_Y + 32, "未选择项目", size=17, weight=600),
        svg.text(
            DETAIL_X + 14,
            BODY_Y + 54,
            "从左侧选择一个项目",
            size=12,
            fill=MUTED,
        ),
        svg.rect(
            DETAIL_X,
            BODY_Y + 104,
            DETAIL_W,
            BODY_H - 104,
            fill=PANEL,
            stroke=LINE,
            r=6,
        ),
        svg.icon(
            "inbox",
            center - 22,
            BODY_Y + 268,
            size=44,
            colour=PLACEHOLDER_ICON,
        ),
        svg.text(
            center,
            BODY_Y + 356,
            "还没有论文项目",
            size=13,
            weight=600,
            anchor="middle",
        ),
        svg.text(
            center,
            BODY_Y + 382,
            "scripts/new-paper.ps1 my-paper --venue NeurIPS --year 2027 --mode conference",
            size=12,
            fill=MUTED,
            family=MONO,
            anchor="middle",
        ),
        svg.text(
            center,
            BODY_Y + 404,
            "创建第一篇后点「刷新」即可在这里看到它。",
            size=12,
            fill=MUTED,
            anchor="middle",
        ),
    )
    chat_panel(svg, configured=False)
    status_bar(svg, "工作流：默认（仓库根）", "凭据可用")
    return svg.render()


def screen_project_ok() -> str:
    svg = Svg(W, H)
    toolbar(svg, "3 个项目 · 1 个无法读取")
    project_list(
        svg,
        [
            ("broken-project", "无法解析 ccfa.yaml"),
            ("example-paper", None),
            ("shadowmem-extension", None),
        ],
        1,
    )
    detail_header(
        svg,
        "example-paper",
        "模式 conference · 更新于 2026-10-05",
        [("阶段 internal-review", False), ("门禁 review_cleared", False), ("截止 2027-02-15", False)],
    )
    action_row(svg, "1 条结果 · 全部通过", OK)
    results_table(svg, [("validate", "OK", "无问题")])
    chat_panel(svg, configured=True)
    status_bar(svg, "工作流：默认（仓库根）", "凭据可用")
    return svg.render()


def screen_blocked() -> str:
    svg = Svg(W, H)
    toolbar(svg, "3 个项目 · 1 个无法读取")
    project_list(
        svg,
        [
            ("broken-project", "无法解析 ccfa.yaml"),
            ("example-paper", None),
            ("shadowmem-extension", None),
        ],
        0,
    )
    detail_header(
        svg,
        "broken-project",
        "项目状态解析失败",
        [("无法读取 broken-project", True), ("配置无效", True), ("截止 未知", False)],
        broken=True,
    )
    action_row(svg, "1 条结果 · 1 条需处理", PROBLEM)
    results_table(
        svg,
        [
            (
                "ccfa.yaml",
                "错误",
                "while parsing a block mapping ... expected <block end>, but found '['",
            )
        ],
    )
    chat_panel(svg, configured=False)
    status_bar(svg, "工作流：默认（仓库根）", "凭据可用")
    return svg.render()


def screen_checkpoints() -> str:
    svg = Svg(W, H)
    toolbar(svg, "1 个 ready · 3 项待人工")
    project_list(
        svg,
        [("example-paper", None), ("shadowmem-extension", None)],
        0,
    )
    checkpoint_panel(
        svg,
        [
            (
                "approve",
                "主证明逐行成立吗？每一步推理与所依赖的假设是否都站得住？",
                "data/proof-audit.yaml",
                "写 reviewer、结论与复核证据路径",
            ),
            (
                "approve",
                "关键引用是否真的支撑它所在的那句论断，而不只是存在？",
                "data/citation-support.yaml",
                "逐条写 supports 与判定依据",
            ),
            (
                "approve",
                "每张图和表是否真的展示了正文声称的效应？",
                "data/figure-support.yaml",
                "逐图写 figure 与判定依据",
            ),
            (
                "feedback",
                "第二位人类编码者完成盲法编码了吗？一致率达到预设门槛了吗？",
                "data/human-coding-report.json",
                "写 coders、agreement、kappa 与分歧裁决",
            ),
        ],
        banner="ready=false：3 项人工复核未完成，其中 1 项阻塞投稿",
    )
    chat_panel(svg, configured=True)
    status_bar(svg, "工作流：默认（仓库根）", "凭据可用")
    return svg.render()


def screen_chat_bubbles() -> str:
    """The conversation column with every message role on screen at once."""

    svg = Svg(W, H)
    toolbar(svg, "3 个项目 · 1 个无法读取")
    project_list(
        svg,
        [
            ("broken-project", "无法解析 ccfa.yaml"),
            ("example-paper", None),
            ("shadowmem-extension", None),
        ],
        1,
    )
    detail_header(
        svg,
        "example-paper",
        "模式 conference · 更新于 2026-10-05",
        [
            ("阶段 internal-review", False),
            ("门禁 review_cleared", False),
            ("截止 2027-02-15", False),
        ],
    )
    action_row(svg, "1 条结果 · 全部通过", OK)
    results_table(svg, [("validate", "OK", "无问题")])
    chat_panel(
        svg,
        configured=True,
        messages=[
            ("user", "RAG 攻击面那节的引用是不是撑不住？"),
            (
                "assistant",
                "4.2 节的 [12] 只证明了检索污染可行：\n"
                "• 支持：污染语料能被检索到\n"
                "• 不支持：端到端攻击成功\n"
                ">assert claim.evidence == \"end-to-end\"",
            ),
            ("tool", "ok"),
            ("tool-denied", "denied"),
            ("error", "引擎超时：provider 60s 内没有返回"),
        ],
    )
    status_bar(svg, "工作流：默认（仓库根）", "凭据可用")
    return svg.render()


def screen_narrow() -> str:
    """The collapsed layout: below the breakpoint the conversation column is
    gone and the detail pane takes over its width."""

    width, height = 900, 700
    svg = Svg(width, height)
    toolbar(svg, "3 个项目 · 1 个无法读取")
    project_list(
        svg,
        [
            ("broken-project", "无法解析 ccfa.yaml"),
            ("example-paper", None),
            ("shadowmem-extension", None),
        ],
        1,
    )
    detail_x = MARGIN + SIDEBAR_W + MARGIN
    detail_w = width - detail_x - MARGIN
    detail_header(
        svg,
        "example-paper",
        "模式 conference · 更新于 2026-10-05",
        [
            ("阶段 internal-review", False),
            ("门禁 review_cleared", False),
            ("截止 2027-02-15", False),
        ],
        x=detail_x,
        w=detail_w,
    )
    action_row(svg, "3 项待人工", PROBLEM, x=detail_x, w=detail_w)
    checkpoint_panel(
        svg,
        [
            (
                "approve",
                "主证明逐行成立吗？每一步推理与所依赖的假设是否都站得住？",
                "data/proof-audit.yaml",
                "写 reviewer、结论与复核证据路径",
            ),
            (
                "approve",
                "关键引用是否真的支撑它所在的那句论断，而不只是存在？",
                "data/citation-support.yaml",
                "逐条写 supports 与判定依据",
            ),
            (
                "feedback",
                "第二位人类编码者完成盲法编码了吗？一致率达到预设门槛了吗？",
                "data/human-coding-report.json",
                "写 coders、agreement、kappa 与分歧裁决",
            ),
        ],
        banner="待人工复核：3 项 · 对话栏已收起",
        x=detail_x,
        w=detail_w,
        y=BODY_Y + 140,
    )
    status_bar(svg, "工作流：默认（仓库根）", "凭据可用")
    return svg.render()


def dialog_settings() -> str:
    w, h = 560, 533
    svg = Svg(w, h, background=CANVAS)
    svg.layer(
        "settings-dialog",
        svg.rect(0, 0, w, h, fill=CANVAS),
        svg.text(16, 32, "设置", size=17, weight=600),
        svg.text(
            16,
            54,
            "API key 只写入系统密钥环，settings.json 里只保存 key 名称。",
            size=11,
            fill=MUTED,
        ),
        svg.text(16, 82, "模型 provider", size=11, fill=MUTED, weight=600),
    )
    rows = [
        ("Provider 名称", ""),
        ("Base URL", ""),
        ("模型", ""),
        ("超时（秒）", "60.00"),
        ("API key", ""),
        ("HTTP 工具", "可选，例如 http-tools.yaml"),
    ]
    y = 96
    field_parts = []
    for label, value in rows:
        field_parts.append(svg.text(16, y + 19, label, size=12))
        field_parts.append(
            svg.rect(150, y, w - 166, 28, fill=PANEL, stroke=FIELD_BORDER, r=6)
        )
        if value:
            field_parts.append(svg.text(160, y + 19, value, size=12, fill=INK))
        y += 36
    field_parts.append(svg.text(16, y + 19, "密钥状态", size=12))
    field_parts.append(
        svg.text(150, y + 19, "未配置", size=12, fill=MUTED)
    )
    field_parts.append(button(svg, w - 100, 96 + 36 * 3, 84, "浏览"))
    svg.layer("provider-form", *field_parts)

    wf_y = y + 40
    svg.layer(
        "workflow-section",
        svg.text(16, wf_y, "工作流", size=11, fill=MUTED, weight=600),
        svg.text(16, wf_y + 31, "工作流目录", size=12),
        svg.rect(150, wf_y + 12, w - 266, 28, fill=PANEL, stroke=FIELD_BORDER, r=6),
        svg.text(
            160,
            wf_y + 31,
            "工作流仓库根目录（含 tools/）",
            size=11,
            fill=MUTED,
        ),
        button(svg, w - 100, wf_y + 12, 84, "浏览"),
        svg.text(16, wf_y + 67, "Python 解释器", size=12),
        svg.rect(150, wf_y + 48, w - 266, 28, fill=PANEL, stroke=FIELD_BORDER, r=6),
        svg.text(160, wf_y + 67, "留空则用 tools/.venv 里的解释器", size=11, fill=MUTED),
        button(svg, w - 100, wf_y + 48, 84, "浏览"),
        button(svg, 150, wf_y + 92, 130, "测试工作流连接"),
        svg.text(w - 16, h - 24, "取消", size=12, anchor="end"),
    )
    svg.layer("settings-actions", button(svg, w - 132, h - 42, 116, "保存", primary=True))
    return svg.render()


SCREENS = {
    "01-workbench-empty.svg": screen_empty,
    "02-workbench-project.svg": screen_project_ok,
    "03-workbench-blocked.svg": screen_blocked,
    "04-human-checkpoints.svg": screen_checkpoints,
    "05-settings-dialog.svg": dialog_settings,
    "06-chat-bubbles.svg": screen_chat_bubbles,
    "07-narrow-collapsed.svg": screen_narrow,
}


def main() -> int:
    out_dir = OUT_DIR if MODE == "light" else OUT_DIR / MODE
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, builder in SCREENS.items():
        target = out_dir / name
        target.write_text(builder(), encoding="utf-8", newline="\n")
        print(f"wrote {target.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
