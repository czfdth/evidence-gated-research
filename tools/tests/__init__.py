"""Shared helpers for tool-side tests."""

from __future__ import annotations

import unittest

from ccfa.latex_compile import find_engine
from newpaper.venues import available_venues, templates_root


def venue_library_available() -> bool:
    return bool(available_venues())


def request_venue_library(testcase: unittest.TestCase) -> None:
    """Skip when the host's private venue-template library is unavailable.

    The derivation end-to-end tests run against a researcher's local
    ``$CODEX_HOME/skills/ccf-latex-templates`` library. That tree is not part of
    this repository and cannot be installed on a clean CI runner, so the tests
    skip with an explicit reason instead of failing there.
    """

    if not venue_library_available():
        testcase.skipTest(
            "host venue template library not found at "
            f"{templates_root()}; these end-to-end tests need the local "
            "$CODEX_HOME/skills/ccf-latex-templates library"
        )


def request_latex_engine(testcase: unittest.TestCase) -> None:
    """Skip when the host has no LaTeX engine to compile real documents."""

    if find_engine() is None:
        testcase.skipTest(
            "host LaTeX engine (pdflatex/xelatex) not found; "
            "these tests compile real documents"
        )
