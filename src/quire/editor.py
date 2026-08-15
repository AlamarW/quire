"""A minimal built-in editor, offered as an alternative to external $EDITOR commands.

Built on Textual, which renders through its own terminal protocol handling (not `curses`,
which is POSIX-only), so this runs unchanged on Windows, WSL/Linux, and macOS -- the only
requirement is a terminal that understands ANSI/VT escape sequences.

quire owns the parts that are the same everywhere: the layout, the save/discard keys, the
two-press discard confirmation, and the guarantee that text is never destroyed. The host
supplies what differs -- what the footer says, and any extra keys -- through `footer` and
`extra_bindings` rather than through flags naming an app.

The host is responsible for *persisting* discarded text, not quire. journ encrypts its
entries and cannot write a plaintext recovery copy the way stet does, so the decision has
to belong to the caller. What quire guarantees is that the caller always receives the text
and never has to ask for it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Static, TextArea

from quire.words import count_words


@dataclass(frozen=True)
class FooterText:
    """What the host wants shown in the status bar for a given word count.

    `emphasis` styles the bar as a success state -- journ uses it for a met writing goal.
    The confirm (error) style is quire's and is not host-controllable; it belongs to the
    discard guard.
    """

    text: str
    emphasis: bool = False


@dataclass(frozen=True)
class ExtraBinding:
    """A host-specific key. `action` mutates the host's own state; quire then cancels any
    pending discard and re-renders the footer, so the host's closure sees the new state."""

    key: str
    description: str
    action: Callable[[], None]


@dataclass
class EditorResult:
    text: str
    """The final text, whether or not it was saved. Present on a discard too, so the caller
    can stash it however its own storage model requires."""
    saved: bool


@dataclass
class _Config:
    footer: Callable[[int], FooterText]
    extra_bindings: tuple[ExtraBinding, ...] = field(default_factory=tuple)


class EditorApp(App):
    # Textual binds ctrl+p to its command palette by default, which would swallow a host
    # binding on that key -- journ uses ctrl+p for its private toggle. Not needed in this
    # minimal, distraction-free editor anyway.
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    TextArea {
        height: 1fr;
    }
    #status {
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    #status.emphasis {
        background: $success;
        color: $text;
    }
    #status.confirm {
        background: $error;
        color: $text;
    }
    """

    # ctrl+s is deliberately avoided -- on Windows it collides with pyreadline3's
    # forward-i-search binding for the host app's shell prompt (and often the terminal's own
    # readline emulation too), which can leave the next prompt stuck in an i-search state
    # after saving. ctrl+shift+s doesn't work as a substitute: Textual's Windows driver reads
    # the console's translated character for a key event, and Windows translates ctrl+s and
    # ctrl+shift+s to the same control character, so they're indistinguishable on this stack.
    # ctrl+w ("write") saves instead. TextArea already binds plain ctrl+w to delete-word-left,
    # and non-priority bindings are checked from the focused widget upward, so TextArea would
    # claim it first without priority=True, which checks this binding from the App down before
    # the focused widget gets a turn.
    #
    # Discarding UNSAVED CHANGES takes two presses (see action_cancel): ctrl+q sits right
    # next to ctrl+w, and a single mistyped discard once cost a real 600-word session.
    # ctrl+q must STAY bound even so -- Textual's own default for ctrl+q is
    # quit-without-confirming, so removing our binding would reintroduce exactly that data
    # loss through the framework.
    BINDINGS = [
        Binding("ctrl+w", "save", "Save", priority=True),
        Binding("ctrl+q", "cancel", "Discard | Exit", priority=True),
        ("escape", "cancel", "Discard & exit"),
    ]

    def __init__(self, initial_text: str, config: _Config):
        super().__init__()
        self.initial_text = initial_text
        self._config = config
        self.result: EditorResult | None = None
        self._confirm_discard = False

    def compose(self) -> ComposeResult:
        yield Static("", id="status")
        yield TextArea(self.initial_text, id="editor", soft_wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        text_area = self.query_one("#editor", TextArea)
        text_area.focus()
        # Cursor otherwise defaults to the document start, which would silently interleave
        # new typing into the middle of existing text instead of appending to it.
        text_area.cursor_location = text_area.document.end
        self._refresh_status(count_words(self.initial_text))

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._confirm_discard = False
        self._refresh_status(count_words(event.text_area.text))

    def _current_text(self) -> str:
        return self.query_one("#editor", TextArea).text

    def _refresh_status(self, word_count: int) -> None:
        status = self.query_one("#status", Static)
        if self._confirm_discard:
            status.update("Unsaved changes -- press again to discard, ctrl+w to save")
            status.set_class(False, "emphasis")
        else:
            rendered = self._config.footer(word_count)
            status.update(rendered.text)
            status.set_class(rendered.emphasis, "emphasis")
        status.set_class(self._confirm_discard, "confirm")

    def action_extra(self, index: int) -> None:
        """Dispatch a host binding. Bound as `extra(N)` because Textual resolves BINDINGS
        off the class, so host callbacks cannot each get their own action method."""
        self._config.extra_bindings[index].action()
        self._confirm_discard = False
        self._refresh_status(count_words(self._current_text()))

    def action_save(self) -> None:
        self.result = EditorResult(text=self._current_text(), saved=True)
        self.initial_text = self.result

    def action_cancel(self) -> None:
        """Discard | exit; but discarding UNSAVED CHANGES takes a second confirming press.
        A clean editor still exits on the first press. Any deliberate action in between
        (typing, saving, a host binding) cancels the pending discard.

        Either way the text comes back to the caller. Deciding it isn't worth keeping is the
        host's call to make, not this editor's."""
        text = self._current_text()
        if text == self.initial_text or self._confirm_discard:
            self.result = EditorResult(text=text, saved=False)
            self.exit()
            return
        self._confirm_discard = True
        self._refresh_status(count_words(text))


def build_editor(
    initial_text: str,
    footer: Callable[[int], FooterText],
    extra_bindings: Sequence[ExtraBinding] = (),
) -> EditorApp:
    """Build a configured editor without running it -- the seam host test suites drive with
    Textual's `run_test()` pilot."""
    extras = tuple(extra_bindings)
    configured = type(
        "ConfiguredEditorApp",
        (EditorApp,),
        {
            "BINDINGS": [
                *EditorApp.BINDINGS,
                *(
                    Binding(binding.key, f"extra({index})", binding.description)
                    for index, binding in enumerate(extras)
                ),
            ]
        },
    )
    return configured(initial_text, _Config(footer=footer, extra_bindings=extras))


def run_editor(
    initial_text: str,
    footer: Callable[[int], FooterText],
    extra_bindings: Sequence[ExtraBinding] = (),
) -> EditorResult:
    """Run the built-in editor. The result always carries the final text; `saved` says
    whether the user chose to keep it."""
    app = build_editor(initial_text, footer, extra_bindings)
    app.run()
    # app.result is None only if the app exited without either action (e.g. a crash);
    # treat that as an unsaved exit carrying the original text so nothing is ever lost.
    return app.result or EditorResult(text=initial_text, saved=False)
