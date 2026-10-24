"""What differs between operating systems, in one place. Everything else is written once and asks here.

`posix.py` is macOS and Linux, `windows.py` is Windows; both name the same things (tests/static/test_host.py checks it).
This is the only place that looks at `os.name`. Standard library only: `tools/local.py` and `desktop/launcher.py` import
it before any virtual environment exists.
"""
from __future__ import annotations

import os

if os.name == "nt":
    from verticals.host.windows import *  # noqa: F401,F403
    from verticals.host.windows import __all__  # noqa: F401
else:
    from verticals.host.posix import *  # noqa: F401,F403
    from verticals.host.posix import __all__  # noqa: F401
