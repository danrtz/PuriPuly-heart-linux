from __future__ import annotations

import sys

from puripuly_heart.core.windows_process_ownership import retain_current_process_job
from puripuly_heart.main import main

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr is not None:
    sys.stderr.reconfigure(encoding="utf-8")

if sys.argv[1:2] == ["run-headless"]:
    retain_current_process_job()
    raise SystemExit(main(sys.argv[1:]))
raise SystemExit(main(["cli", *sys.argv[1:]]))
