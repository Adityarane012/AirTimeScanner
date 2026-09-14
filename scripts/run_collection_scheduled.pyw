"""Task Scheduler entrypoint: run_collection.py with no console window.

Launched by `pythonw.exe` (see register_task.ps1). It replaces
run_collection.bat, which ran the collector in a cmd console. Under the
task's interactive logon that console opened on the desktop a few minutes
after login, blank because all output went to the log file, and stayed open
while the collector fetched. Two runs are known to have been killed that way:
LastTaskResult 0xC000013A ("terminated by Ctrl+C or console close") and a
`^C^C` written into logs/collection.log on 09-12 and 09-13. `pythonw` never
creates a console, so there is nothing to close.

`pythonw` also has no stdout or stderr, so this launcher provides them: it
changes to the repo root (settings reads `.env` and `data/raw` relative to the
working directory) and points both streams at logs/collection.log *before*
the collector is imported. The order matters, because scrapling's log handler
captures `sys.stderr` when it is created.

An uncaught exception is written to the log with its traceback and turned
into exit code 1, so it shows up as LastTaskResult instead of vanishing.
Manual runs should keep using `python scripts/run_collection.py`, which prints
to the terminal.
"""

import os
import runpy
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COLLECTOR = REPO_ROOT / "scripts" / "run_collection.py"
LOG_PATH = REPO_ROOT / "logs" / "collection.log"


def main() -> int:
    os.chdir(REPO_ROOT)
    LOG_PATH.parent.mkdir(exist_ok=True)

    with open(LOG_PATH, "a", encoding="utf-8", buffering=1) as log:
        sys.stdout = sys.stderr = log
        sys.argv = [str(COLLECTOR), *sys.argv[1:]]
        try:
            runpy.run_path(str(COLLECTOR), run_name="__main__")
        except SystemExit as exc:
            if exc.code is None or isinstance(exc.code, int):
                return exc.code or 0
            print(exc.code)
            return 1
        except BaseException:  # noqa: BLE001 - last line of defence; nothing else would record it
            traceback.print_exc()
            return 1
        finally:
            # Restore pythonw's (absent) streams before the file closes, so
            # nothing at interpreter shutdown writes to a closed file.
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
    return 0


if __name__ == "__main__":
    sys.exit(main())
