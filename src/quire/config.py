"""Text-editor resolution, shared by every quire app.

quire owns the resolution rules -- $EDITOR wins, then a saved choice, then (on Windows) an
interactive picker. The host app supplies its own name and paths through an
`EditorEnvironment`.

Build that environment at *call* time rather than import time. Both journ and stet keep
module-level path globals that their test suites monkeypatch, and an environment captured
at import would pin the real ~/.journ or ~/.stet directory before the patch lands.
"""

from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


def _plain(text: str) -> str:
    return text


@dataclass(frozen=True)
class EditorEnvironment:
    """Everything quire needs from the host app to resolve an editor.

    `cmd` renders a suggested command the way the user should actually type it, so a
    suggestion reads `stet editor set` from the shell prompt and `editor set` inside the
    app's own REPL. It is injected rather than imported so that quire.config stays
    importable without the Rich stack, which is why journ and stet both deferred their
    `ui` import inside `get_editor` before this moved into quire.
    """

    app_name: str
    config_dir: Path
    editor_config_filepath: Path
    cmd: Callable[[str], str] = _plain

    @property
    def builtin_editor(self) -> str:
        """The sentinel stored in editor.cfg meaning "use the built-in editor".

        The f-string reproduces the literals journ and stet already have written to disk
        (`__journ_builtin__`, `__stet_builtin__`), so existing configs keep resolving.
        """
        return f"__{self.app_name}_builtin__"

    @property
    def editor_choices(self) -> list[tuple[str, str]]:
        return [
            (
                self.builtin_editor,
                f"{self.app_name}'s built-in editor (distraction-free, live word count)",
            ),
            ("notepad", "Notepad (built into Windows)"),
            ("code --wait", "Visual Studio Code"),
            ("notepad++", "Notepad++"),
            ("subl --wait", "Sublime Text"),
            ("vim", "Vim"),
        ]


def read_saved_editor(env: EditorEnvironment) -> str | None:
    if env.editor_config_filepath.is_file():
        saved_editor = env.editor_config_filepath.read_text(encoding="utf-8").strip()
        if saved_editor:
            return saved_editor
    return None


def save_editor_choice(env: EditorEnvironment, editor_command: str) -> None:
    env.config_dir.mkdir(parents=True, exist_ok=True)
    env.editor_config_filepath.write_text(editor_command, encoding="utf-8")


def prompt_editor_choice(env: EditorEnvironment) -> str:
    """Interactively pick an editor. Used both by the automatic Windows first-run prompt
    and by the explicit `<app> editor set` command on any platform."""
    print(f"Pick a text editor for {env.app_name} to use (this choice is saved for next time):\n")

    available_choices = []
    for command, label in env.editor_choices:
        executable = command.split(" ")[0]
        is_builtin = executable == env.builtin_editor
        is_notepad_on_windows = executable == "notepad" and os.name == "nt"
        if is_builtin or is_notepad_on_windows or shutil.which(executable):
            available_choices.append((command, label))

    for index, (command, label) in enumerate(available_choices, start=1):
        suffix = "" if command == env.builtin_editor else f"  ({command})"
        print(f"  {index}. {label}{suffix}")
    custom_choice_number = len(available_choices) + 1
    print(f"  {custom_choice_number}. Enter a custom command")

    while True:
        choice = input("Choice -> ").strip()
        try:
            choice_number = int(choice)
        except ValueError:
            print("Please enter a number")
            continue

        if 1 <= choice_number <= len(available_choices):
            return available_choices[choice_number - 1][0]
        elif choice_number == custom_choice_number:
            custom_command = input("Enter the editor command (e.g. 'code --wait') -> ").strip()
            if custom_command:
                return custom_command
        else:
            print("Invalid choice, try again")


def get_editor(env: EditorEnvironment) -> str:
    """Resolve the text editor to use: EDITOR env var, saved choice, or (on Windows) a picker."""
    editor = os.getenv("EDITOR")
    if editor:
        return editor

    saved_editor = read_saved_editor(env)
    if saved_editor:
        return saved_editor

    if os.name == "nt":
        print("No EDITOR environment variable is set.")
        chosen_editor = prompt_editor_choice(env)
        save_editor_choice(env, chosen_editor)
        label = (
            f"{env.app_name}'s built-in editor"
            if chosen_editor == env.builtin_editor
            else chosen_editor
        )
        print(
            f"Using {label} going forward. Change it anytime with `{env.cmd('editor set')}`, "
            f"by setting $env:EDITOR, or by deleting {env.editor_config_filepath}\n"
        )
        return chosen_editor

    print(
        "No EDITOR environment variable set, defaulting to 'nano'. Set EDITOR to use a "
        f"different editor, or run `{env.cmd('editor set')}` to pick one (including "
        f"{env.app_name}'s built-in editor)."
    )
    return "nano"


def editor_argv(editor: str) -> list[str]:
    """Split an EDITOR command string into argv, respecting platform quoting conventions."""
    is_windows = os.name == "nt"
    tokens = shlex.split(editor, posix=not is_windows)
    if is_windows:
        # shlex's non-posix mode (needed to preserve Windows path backslashes) does not
        # strip the quote characters it uses for tokenization, unlike posix mode.
        tokens = [t[1:-1] if len(t) >= 2 and t[0] == '"' and t[-1] == '"' else t for t in tokens]
    return tokens
