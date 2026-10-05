"""Visual theme for the workbench.

The workbench is an operations surface: you open it to answer "what is the
state of my paper, and what is blocked". The palette is therefore quiet greys
with a single accent, panels are separated by hairlines rather than shadows,
and colour is reserved for state (problem / advisory / ok).

Two modes ship: ``light`` and ``dark``. Everything the stylesheet paints comes
from the mode's palette, so adding a token here is the only way to add a colour
to the UI. This module stays free of Qt imports on purpose: the design mockup
generator loads it by file with any interpreter, and ``appearance.py`` owns the
Qt side of choosing a mode.
"""

from __future__ import annotations

SANS = 'Inter, "Segoe UI", "Microsoft YaHei UI", sans-serif'
MONO = '"JetBrains Mono", Consolas, "Cascadia Mono", monospace'

# Palette follows the Modex-MH-Agent desktop reference (Tailwind v4 + Inter):
# one vivid indigo primary, Tailwind-family semantics, neutral greys.
LIGHT = {
    "accent": "#625fff",
    "accent_hover": "#4f46e5",
    "ink": "#1a1a1f",
    "muted": "#71717a",
    "line": "#e4e4e7",
    "canvas": "#f7f7f8",
    "panel": "#ffffff",
    "problem": "#d92d20",
    "advisory": "#b45309",
    "ok": "#067647",
    "chip": "#f2f4f7",
    "field_border": "#d0d5dd",
    "button_hover": "#f2f4f7",
    "button_pressed": "#e9edf2",
    "button_disabled": "#f4f5f7",
    "table_header": "#fafbfc",
    "row_hover": "#f8f9fb",
    "row_selected": "#eef1ff",
    "table_selected": "#e8f0fe",
    "gridline": "#eef0f3",
    "badge_problem_bg": "#fef3f2",
    "badge_problem_border": "#fecdca",
    "badge_advisory_bg": "#fffaeb",
    "badge_advisory_border": "#fedf89",
    "banner_pending_bg": "#fffaeb",
    "banner_pending_border": "#fedf89",
    "banner_ok_bg": "#ecfdf3",
    "banner_ok_border": "#a6f4c5",
    "banner_muted_bg": "#f2f4f7",
    "scroll_handle": "#d0d5dd",
    "separator": "#d0d5dd",
    "placeholder_icon": "#c9c9d1",
    "selection": "#cfe0ff",
    "code_bg": "#eef0f3",
}

DARK = {
    "accent": "#7c7aff",
    "accent_hover": "#6b68f5",
    "ink": "#f2f2f5",
    "muted": "#a1a1aa",
    "line": "#2e2e37",
    "canvas": "#141419",
    "panel": "#1e1e24",
    "problem": "#ff7b72",
    "advisory": "#f5b544",
    "ok": "#3ddc97",
    "chip": "#26262e",
    "field_border": "#3a3a45",
    "button_hover": "#2a2a33",
    "button_pressed": "#33333d",
    "button_disabled": "#232329",
    "table_header": "#232329",
    "row_hover": "#24242b",
    "row_selected": "#2b2b45",
    "table_selected": "#2f3150",
    "gridline": "#2a2a33",
    "badge_problem_bg": "#3a1f1f",
    "badge_problem_border": "#6b2b2b",
    "badge_advisory_bg": "#3a2f16",
    "badge_advisory_border": "#6b5525",
    "banner_pending_bg": "#33290f",
    "banner_pending_border": "#6b5525",
    "banner_ok_bg": "#123526",
    "banner_ok_border": "#1f5f45",
    "banner_muted_bg": "#26262e",
    "scroll_handle": "#3f3f4a",
    "separator": "#3f3f4a",
    "placeholder_icon": "#55555f",
    "selection": "#3a3f6b",
    "code_bg": "#2b2b34",
}

PALETTES = {"light": LIGHT, "dark": DARK}
DEFAULT_MODE = "light"

# Legacy names keep the light palette so existing importers stay valid.
ACCENT = LIGHT["accent"]
ACCENT_HOVER = LIGHT["accent_hover"]
INK = LIGHT["ink"]
MUTED = LIGHT["muted"]
LINE = LIGHT["line"]
CANVAS = LIGHT["canvas"]
PANEL = LIGHT["panel"]
PROBLEM = LIGHT["problem"]
ADVISORY = LIGHT["advisory"]
OK = LIGHT["ok"]

STATUS_CODES = {
    "problem": "problem",
    "error": "problem",
    "问题": "problem",
    "错误": "problem",
    "advisory": "advisory",
    "警告": "advisory",
    "approve": "accent",
    "feedback": "advisory",
    # Readiness dimensions and gate verdicts.
    "blocked": "advisory",
    "not-run": "advisory",
    "not-claimed": "advisory",
    "pending-human-review": "advisory",
    "independent-evidence-present": "ok",
    "human-attested": "ok",
    "missing-human-evidence": "problem",
    "invalid-attestation": "problem",
    "ok": "ok",
    "OK": "ok",
}

# Kept for callers that read the light severity map directly.
STATUS_COLORS = {key: LIGHT[token] for key, token in STATUS_CODES.items()}


def normalise_mode(mode: object) -> str:
    """Map anything to a known mode name; unknown values fall back to light."""

    text = str(mode or "").strip().casefold()
    return "dark" if text == "dark" else "light"


def palette(mode: object = DEFAULT_MODE) -> dict:
    return dict(PALETTES[normalise_mode(mode)])


def severity_color(code: object, mode: object = DEFAULT_MODE) -> str:
    """Map a problem code / severity label to a text colour."""

    colors = PALETTES[normalise_mode(mode)]
    text = str(code or "").strip()
    if text in STATUS_CODES:
        return colors[STATUS_CODES[text]]
    lowered = text.casefold()
    if any(token in lowered for token in ("error", "invalid", "missing", "fail")):
        return colors["problem"]
    if "advis" in lowered or "warn" in lowered:
        return colors["advisory"]
    if lowered in {"ok", "pass", "verified"}:
        return colors["ok"]
    return colors["ink"]


def stylesheet(mode: object = DEFAULT_MODE) -> str:
    p = palette(mode)
    return f"""
    QWidget {{
        font-family: {SANS};
        font-size: 9pt;
        color: {p['ink']};
    }}
    QMainWindow, QDialog {{ background: {p['canvas']}; }}

    QFrame#toolbar {{
        background: {p['panel']};
        border-bottom: 1px solid {p['line']};
    }}
    QFrame#card {{
        background: {p['panel']};
        border: 1px solid {p['line']};
        border-radius: 6px;
    }}
    QLabel#sectionTitle {{
        color: {p['muted']};
        font-weight: 600;
    }}
    QLabel#projectTitle {{
        font-size: 12pt;
        font-weight: 600;
    }}
    QLabel#appTitle {{
        font-size: 10pt;
        font-weight: 600;
    }}
    QLabel#placeholderTitle {{
        font-size: 12pt;
        font-weight: 600;
        color: {p['ink']};
    }}
    QLabel#placeholderHint {{
        color: {p['muted']};
    }}
    QLabel#dialogTitle {{
        font-size: 13pt;
        font-weight: 600;
    }}
    QLabel[role="hint"] {{ color: {p['muted']}; }}
    QLabel[role="badge"] {{
        background: {p['chip']};
        border: 1px solid {p['line']};
        border-radius: 4px;
        padding: 2px 8px;
        color: {p['ink']};
    }}
    QLabel[role="badge"][state="problem"] {{
        background: {p['badge_problem_bg']};
        border-color: {p['badge_problem_border']};
        color: {p['problem']};
    }}
    QLabel[role="badge"][state="advisory"] {{
        background: {p['badge_advisory_bg']};
        border-color: {p['badge_advisory_border']};
        color: {p['advisory']};
    }}
    QLabel[role="badge"][state="ok"] {{
        background: {p['banner_ok_bg']};
        border-color: {p['banner_ok_border']};
        color: {p['ok']};
    }}

    QFrame#chatBubble {{
        background: {p['panel']};
        border: 1px solid {p['line']};
        border-radius: 6px;
    }}
    QFrame#chatBubble[role="user"] {{
        background: {p['row_selected']};
    }}
    QFrame#chatBubble[role="tool"] {{
        background: {p['chip']};
    }}
    QFrame#chatBubble[role="error"] {{
        background: {p['badge_problem_bg']};
        border-color: {p['badge_problem_border']};
    }}
    QFrame#chatBubble[role="stopped"] {{
        background: {p['banner_pending_bg']};
        border-color: {p['banner_pending_border']};
    }}
    QLabel#chatRole {{
        color: {p['muted']};
        font-weight: 600;
    }}
    QFrame#chatBubble[role="user"] QLabel#chatRole {{ color: {p['accent']}; }}
    QFrame#chatBubble[role="error"] QLabel#chatRole {{ color: {p['problem']}; }}
    QFrame#chatBubble[role="stopped"] QLabel#chatRole {{ color: {p['advisory']}; }}
    QLabel#chatBody, QTextBrowser#chatBody {{
        color: {p['ink']};
        background: transparent;
        border: none;
    }}
    QLabel#chatChip {{
        background: {p['panel']};
        border: 1px solid {p['line']};
        border-radius: 4px;
        padding: 1px 6px;
        color: {p['muted']};
    }}
    QLabel#chatChip[state="ok"] {{
        background: {p['banner_ok_bg']};
        border-color: {p['banner_ok_border']};
        color: {p['ok']};
    }}
    QLabel#chatChip[state="problem"] {{
        background: {p['badge_problem_bg']};
        border-color: {p['badge_problem_border']};
        color: {p['problem']};
    }}
    QLabel#chatChip[state="advisory"] {{
        background: {p['badge_advisory_bg']};
        border-color: {p['badge_advisory_border']};
        color: {p['advisory']};
    }}

    QPushButton {{
        background: {p['panel']};
        border: 1px solid {p['field_border']};
        border-radius: 6px;
        padding: 4px 12px;
        min-height: 22px;
    }}
    QPushButton:hover {{ background: {p['button_hover']}; }}
    QPushButton:pressed {{ background: {p['button_pressed']}; }}
    QPushButton:disabled {{
        color: {p['muted']};
        background: {p['button_disabled']};
    }}
    QPushButton[role="primary"] {{
        background: {p['accent']};
        border-color: {p['accent']};
        color: white;
        font-weight: 600;
    }}
    QPushButton[role="primary"]:hover {{ background: {p['accent_hover']}; }}
    QLabel#mono {{ font-family: {MONO}; }}
    QLabel#projectNote {{ color: {p['muted']}; }}
    QLabel#statusSeparator {{ color: {p['separator']}; }}
    QLabel#checkpoint_banner {{
        border-radius: 6px;
        padding: 8px 12px;
    }}
    QLabel#checkpoint_banner[state="pending"] {{
        background: {p['banner_pending_bg']};
        border: 1px solid {p['banner_pending_border']};
        color: {p['advisory']};
    }}
    QLabel#checkpoint_banner[state="ok"] {{
        background: {p['banner_ok_bg']};
        border: 1px solid {p['banner_ok_border']};
        color: {p['ok']};
    }}
    QLabel#checkpoint_banner[state="muted"] {{
        background: {p['banner_muted_bg']};
        border: 1px solid {p['line']};
        color: {p['muted']};
    }}
    QFrame#checkpointCard {{
        background: {p['panel']};
        border: 1px solid {p['line']};
        border-radius: 6px;
    }}
    QScrollArea#checkpoint_scroll {{ background: transparent; border: none; }}
    QWidget#checkpoint_container {{ background: transparent; }}
    QLabel#checkpointQuestion {{
        font-size: 10pt;
    }}
    QLabel#checkpointMeta {{
        color: {p['muted']};
        font-family: {MONO};
        font-size: 8pt;
    }}

    QListWidget {{
        background: {p['panel']};
        border: 1px solid {p['line']};
        border-radius: 6px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 5px 6px;
        border-radius: 4px;
    }}
    QListWidget::item:hover {{
        background: {p['row_hover']};
    }}
    QListWidget::item:selected {{
        background: {p['row_selected']};
        color: {p['ink']};
        border-left: 2px solid {p['accent']};
    }}

    QTableWidget {{
        background: {p['panel']};
        border: 1px solid {p['line']};
        border-radius: 6px;
        gridline-color: {p['gridline']};
    }}
    QHeaderView::section {{
        background: {p['table_header']};
        border: none;
        border-bottom: 1px solid {p['line']};
        padding: 4px 6px;
        color: {p['muted']};
        font-weight: 600;
    }}
    QTableWidget::item:selected {{ background: {p['table_selected']}; color: {p['ink']}; }}
    QTableWidget::item:hover {{ background: {p['row_hover']}; }}

    QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {p['panel']};
        border: 1px solid {p['field_border']};
        border-radius: 6px;
        padding: 3px 6px;
        selection-background-color: {p['selection']};
    }}
    QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus {{
        border-color: {p['accent']};
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 18px;
        border: none;
        background: transparent;
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border;
        subcontrol-position: bottom right;
        width: 18px;
        border: none;
        background: transparent;
    }}
    QStatusBar {{ background: {p['panel']}; border-top: 1px solid {p['line']}; }}
    QSplitter::handle {{ background: {p['canvas']}; }}
    QSplitter::handle:horizontal {{ width: 8px; }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {p['scroll_handle']};
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
        width: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    """
