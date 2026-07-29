from quire import terminal


def test_clear_screen_uses_cls_on_windows(monkeypatch):
    issued = []
    monkeypatch.setattr(terminal.os, "name", "nt")
    monkeypatch.setattr(terminal.os, "system", issued.append)
    terminal.clear_screen()
    assert issued == ["cls"]


def test_clear_screen_uses_clear_elsewhere(monkeypatch):
    issued = []
    monkeypatch.setattr(terminal.os, "name", "posix")
    monkeypatch.setattr(terminal.os, "system", issued.append)
    terminal.clear_screen()
    assert issued == ["clear"]
