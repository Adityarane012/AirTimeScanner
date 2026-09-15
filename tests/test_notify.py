"""The notifier's two rules: never raise, never open a window.

No real toast is shown here; subprocess is replaced, so these run anywhere.
"""

import subprocess

from apix.ops import notify as notify_module
from apix.ops.notify import BODY_ENV, TITLE_ENV, notify


class _Recorder:
    def __init__(self, returncode=0, raises=None):
        self.calls = []
        self.returncode = returncode
        self.raises = raises

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(args, self.returncode)


def _on_windows(monkeypatch, recorder):
    monkeypatch.setattr(notify_module.sys, "platform", "win32")
    monkeypatch.setattr(notify_module.subprocess, "run", recorder)


def test_a_shown_notification_reports_true(monkeypatch):
    recorder = _Recorder()
    _on_windows(monkeypatch, recorder)
    assert notify("APIx", "hello") is True


def test_a_missing_powershell_is_swallowed(monkeypatch):
    """A notification failure must never turn a good collection run into a
    crashed one."""
    _on_windows(monkeypatch, _Recorder(raises=FileNotFoundError("powershell.exe")))
    assert notify("APIx", "hello") is False


def test_a_hung_powershell_is_swallowed(monkeypatch):
    _on_windows(monkeypatch, _Recorder(raises=subprocess.TimeoutExpired("powershell.exe", 20)))
    assert notify("APIx", "hello") is False


def test_a_failing_toast_reports_false(monkeypatch):
    _on_windows(monkeypatch, _Recorder(returncode=1))
    assert notify("APIx", "hello") is False


def test_off_windows_it_does_nothing(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(notify_module.sys, "platform", "linux")
    monkeypatch.setattr(notify_module.subprocess, "run", recorder)
    assert notify("APIx", "hello") is False
    assert recorder.calls == []


def test_powershell_is_launched_without_a_console_window(monkeypatch):
    """The collector runs under pythonw so no console appears. A child
    powershell.exe without CREATE_NO_WINDOW would bring one straight back."""
    recorder = _Recorder()
    _on_windows(monkeypatch, recorder)
    notify("APIx", "hello")
    _, kwargs = recorder.calls[0]
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert "timeout" in kwargs


def test_message_text_is_passed_as_data_not_as_code(monkeypatch):
    """Alert text includes error messages from remote servers. It goes
    through the environment, never spliced into the -Command script."""
    hostile = "boom'); Remove-Item C:\\ -Recurse; $(calc) #"
    recorder = _Recorder()
    _on_windows(monkeypatch, recorder)

    notify("APIx", hostile)

    args, kwargs = recorder.calls[0]
    assert all(hostile not in arg for arg in args)
    assert kwargs["env"][BODY_ENV] == hostile
    assert kwargs["env"][TITLE_ENV] == "APIx"
