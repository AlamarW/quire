import pytest

from quire import config


@pytest.fixture(autouse=True)
def no_inherited_editor(monkeypatch):
    """A real $EDITOR in the developer's shell would short-circuit every resolution test."""
    monkeypatch.delenv("EDITOR", raising=False)


@pytest.fixture
def env(tmp_path):
    config_dir = tmp_path / ".testapp"
    return config.EditorEnvironment(
        app_name="testapp",
        config_dir=config_dir,
        editor_config_filepath=config_dir / "editor.cfg",
    )


class TestBuiltinEditorSentinel:
    """The sentinel is derived from the app name, but journ and stet already have the
    literal strings written into ~/.journ/editor.cfg and ~/.stet/editor.cfg. Deriving a
    different value would silently drop a saved choice back to the picker."""

    def test_matches_the_value_journ_already_wrote_to_disk(self, tmp_path):
        env = config.EditorEnvironment(
            app_name="journ", config_dir=tmp_path, editor_config_filepath=tmp_path / "e.cfg"
        )
        assert env.builtin_editor == "__journ_builtin__"

    def test_matches_the_value_stet_already_wrote_to_disk(self, tmp_path):
        env = config.EditorEnvironment(
            app_name="stet", config_dir=tmp_path, editor_config_filepath=tmp_path / "e.cfg"
        )
        assert env.builtin_editor == "__stet_builtin__"


class TestGetEditor:
    def test_env_var_wins(self, env, monkeypatch):
        monkeypatch.setenv("EDITOR", "nvim")
        config.save_editor_choice(env, "notepad")
        assert config.get_editor(env) == "nvim"

    def test_saved_choice_used_when_no_env(self, env):
        config.save_editor_choice(env, "code --wait")
        assert config.get_editor(env) == "code --wait"

    def test_posix_defaults_to_nano(self, env, monkeypatch):
        monkeypatch.setattr(config.os, "name", "posix")
        assert config.get_editor(env) == "nano"

    def test_windows_prompts_and_saves(self, env, monkeypatch):
        monkeypatch.setattr(config.os, "name", "nt")
        monkeypatch.setattr("builtins.input", lambda *args: "1")
        assert config.get_editor(env) == env.builtin_editor
        assert config.read_saved_editor(env) == env.builtin_editor


class TestInjectedCmd:
    """The host app renders suggested commands; quire must not hardcode a prefix."""

    def test_suggestion_uses_the_hosts_formatter(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(config.os, "name", "posix")
        env = config.EditorEnvironment(
            app_name="stet",
            config_dir=tmp_path,
            editor_config_filepath=tmp_path / "editor.cfg",
            cmd=lambda text: f"stet {text}",
        )
        config.get_editor(env)
        assert "`stet editor set`" in capsys.readouterr().out

    def test_defaults_to_the_bare_command(self, env, monkeypatch, capsys):
        monkeypatch.setattr(config.os, "name", "posix")
        config.get_editor(env)
        assert "`editor set`" in capsys.readouterr().out


class TestSavedEditor:
    def test_roundtrip(self, env):
        config.save_editor_choice(env, "vim")
        assert config.read_saved_editor(env) == "vim"

    def test_missing_file_returns_none(self, env):
        assert config.read_saved_editor(env) is None

    def test_blank_file_returns_none(self, env):
        config.save_editor_choice(env, "   ")
        assert config.read_saved_editor(env) is None


class TestEditorArgv:
    def test_posix_splitting(self, monkeypatch):
        monkeypatch.setattr(config.os, "name", "posix")
        assert config.editor_argv("code --wait") == ["code", "--wait"]

    def test_windows_quoted_path_with_spaces(self, monkeypatch):
        monkeypatch.setattr(config.os, "name", "nt")
        argv = config.editor_argv('"C:\\Program Files\\Notepad++\\notepad++.exe" -multiInst')
        assert argv == ["C:\\Program Files\\Notepad++\\notepad++.exe", "-multiInst"]

    def test_windows_backslashes_preserved(self, monkeypatch):
        monkeypatch.setattr(config.os, "name", "nt")
        assert config.editor_argv("C:\\tools\\vim.exe") == ["C:\\tools\\vim.exe"]
