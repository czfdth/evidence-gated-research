"""``python -m ccfa <command>`` entry point.

Defined without a top-level ``main()`` on purpose: ``tools/tests/test_scripts``
treats every ``ccfa`` module that defines ``main()`` as a console tool that must
have a PowerShell wrapper, and this module is an entry point, not a tool.
"""

from __future__ import annotations

from ccfa.dispatch import run

raise SystemExit(run())
