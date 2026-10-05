"""Visual theme for the workbench.

The workbench is an operations surface: you open it to answer "what is the
state of my paper, and what is blocked". The palette is therefore quiet greys
with a single accent, panels are separated by hairlines rather than shadows,
and colour is reserved for state (problem / advisory / ok).
"""

from __future__ import annotations

# Palette follows the Modex-MH-Agent desktop reference (Tailwind v4 + Inter):
# one vivid indigo primary, Tailwind-family semantics, neutral greys.
ACCENT = "#625fff"
ACCENT_HOVER = "#4f46e5"
INK = "#1a1a1f"
MUTED = "#71717a"
LINE = "#e4e4e7"
CANVAS = "#f7f7f8"
PANEL = "#ffffff"

PROBLEM = "#d92d20"
ADVISORY = "#b45309"
OK = "#067647"

SANS = 'Inter, "Segoe UI", "Microsoft YaHei UI", sans-serif'
MONO = '"JetBrains Mono", Consolas, "Cascadia Mono", monospace'

STATUS_COLORS = {
    "problem": PROBLEM,
    "error": PROBLEM,
    "问题": PROBLEM,
    "错误": PROBLEM,
    "advisory": ADVISORY,
    "警告": ADVISORY,
    "ok": OK,
    "OK": OK,
}


def severity_color(code: object) -> str:
    """Map a problem code / severity label to a text colour."""

    text = str(code or "").strip()
    if text in STATUS_COLORS:
        return STATUS_COLORS[text]
    lowered = text.casefold()
    if any(token in lowered for token in ("error", "invalid", "missing", "fail")):
        return PROBLEM
    if "advis" in lowered or "warn" in lowered:
        return ADVISORY
    if lowered in {"ok", "pass", "verified"}:
        return OK
    return INK


def stylesheet() -> str:
    return f"""
    QWidget {{
        font-family: {SANS};
        font-size: 9pt;
        color: {INK};
    }}
    QMainWindow, QDialog {{ background: {CANVAS}; }}

    QFrame#toolbar {{
        background: {PANEL};
        border-bottom: 1px solid {LINE};
    }}
    QFrame#card {{
        background: {PANEL};
        border: 1px solid {LINE};
        border-radius: 6px;
    }}
    QLabel#sectionTitle {{
        color: {MUTED};
        font-weight: 600;
    }}
    QLabel#projectTitle {{
        font-size: 12pt;
        font-weight: 600;
    }}
    QLabel#dialogTitle {{
        font-size: 13pt;
        font-weight: 600;
    }}
    QLabel[role="hint"] {{ color: {MUTED}; }}
    QLabel[role="badge"] {{
        background: #f2f4f7;
        border: 1px solid {LINE};
        border-radius: 4px;
        padding: 2px 8px;
        color: {INK};
    }}
    QLabel[role="badge"][state="problem"] {{
        background: #fef3f2;
        border-color: #fecdca;
        color: {PROBLEM};
    }}

    QPushButton {{
        background: {PANEL};
        border: 1px solid #d0d5dd;
        border-radius: 6px;
        padding: 4px 12px;
        min-height: 22px;
    }}
    QPushButton:hover {{ background: #f2f4f7; }}
    QPushButton:pressed {{ background: #e9edf2; }}
    QPushButton:disabled {{ color: {MUTED}; background: #f4f5f7; }}
    QPushButton[role="primary"] {{
        background: {ACCENT};
        border-color: {ACCENT};
        color: white;
        font-weight: 600;
    }}
    QPushButton[role="primary"]:hover {{ background: {ACCENT_HOVER}; }}
    QLabel#mono {{ font-family: {MONO}; }}
    QLabel#projectNote {{ color: {MUTED}; }}
    QLabel#statusSeparator {{ color: #d0d5dd; }}

    QListWidget {{
        background: {PANEL};
        border: 1px solid {LINE};
        border-radius: 6px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 5px 6px;
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background: #e8f0fe;
        color: {INK};
    }}

    QTableWidget {{
        background: {PANEL};
        border: 1px solid {LINE};
        border-radius: 6px;
        gridline-color: #eef0f3;
    }}
    QHeaderView::section {{
        background: #fafbfc;
        border: none;
        border-bottom: 1px solid {LINE};
        padding: 4px 6px;
        color: {MUTED};
        font-weight: 600;
    }}
    QTableWidget::item:selected {{ background: #e8f0fe; color: {INK}; }}

    QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {PANEL};
        border: 1px solid #d0d5dd;
        border-radius: 6px;
        padding: 3px 6px;
        selection-background-color: #cfe0ff;
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
    QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus {{
        border-color: {ACCENT};
    }}
    QStatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; }}
    QSplitter::handle {{ background: {CANVAS}; }}
    QSplitter::handle:horizontal {{ width: 8px; }}
    """
