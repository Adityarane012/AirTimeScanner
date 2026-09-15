"""Best-effort desktop notification, so a broken collector comes to you.

A missed-day check that only runs when someone runs it would not have caught
the 09-10 to 09-14 gap any sooner. This raises a Windows toast from inside the
collector instead. It uses PowerShell and the WinRT toast API, so no extra
dependency is needed.

Two rules, both learned from the collector itself:

- **Never raise.** A notification failure must not turn a successful
  collection into a failed one. Every alert is also printed to the collection
  log, so a toast that does not appear loses nothing.
- **Never open a window.** The collector runs under `pythonw` precisely so
  that no console appears (register_task.ps1). A child `powershell.exe`
  without CREATE_NO_WINDOW would bring the console back.

The text travels in environment variables, not on the command line, so an
error message containing quotes or `$(...)` is data, never PowerShell code.
"""

from __future__ import annotations

import os
import subprocess
import sys

TITLE_ENV = "APIX_TOAST_TITLE"
BODY_ENV = "APIX_TOAST_BODY"

# Toasts need a registered AppUserModelID. Windows PowerShell's is present on
# every Windows install, which avoids registering one of our own.
_POWERSHELL_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

_TOAST_SCRIPT = f"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$doc = [xml]'<toast><visual><binding template="ToastGeneric"><text/><text/></binding></visual></toast>'
$nodes = $doc.SelectNodes('//text')
$nodes[0].InnerText = $env:{TITLE_ENV}
$nodes[1].InnerText = $env:{BODY_ENV}
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($doc.OuterXml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_POWERSHELL_APP_ID}').Show($toast)
"""


def notify(title: str, message: str, *, timeout_s: float = 20.0) -> bool:
    """Show a desktop notification. Returns whether it was shown; never raises.

    Synchronous with a timeout, not fire-and-forget: the collector exits right
    after, and a child it did not wait for could be torn down with the task.
    The toast stays in the notification centre after PowerShell exits.
    """
    if sys.platform != "win32":
        return False

    env = {**os.environ, TITLE_ENV: title[:200], BODY_ENV: message[:1000]}
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _TOAST_SCRIPT,
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0
