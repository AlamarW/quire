"""quire owns the editor's guarantees: the two-press discard confirmation, and that text
always comes back to the caller. What the footer says and which extra keys exist belong to
the host app and are tested there."""

from quire.editor import EditorResult, ExtraBinding, FooterText, build_editor


def plain_footer(word_count: int) -> FooterText:
    return FooterText(text=f"{word_count} words")


def editor(initial_text: str = "existing text", **kwargs):
    kwargs.setdefault("footer", plain_footer)
    return build_editor(initial_text, **kwargs)


class TestSaving:
    async def test_typing_appends_at_the_cursor_end_not_the_start(self):
        app = editor()
        async with app.run_test() as pilot:
            await pilot.press(*" more")
            await pilot.press("ctrl+w")
            await pilot.pause()

        assert app.result == EditorResult(text="existing text more", saved=True)

    async def test_ctrl_w_saves_even_while_a_discard_is_pending(self):
        app = editor()
        async with app.run_test() as pilot:
            await pilot.press(*" more")
            await pilot.press("escape")
            await pilot.press("ctrl+w")
            await pilot.pause()

        assert app.result.saved is True
        assert app.result.text == "existing text more"


class TestDiscardGuard:
    """A mistyped ctrl+q once cost a real 600-word session. These are the tests that keep
    that from being reintroduced -- in either app, now that there is only one copy."""

    async def test_clean_editor_exits_on_the_first_press(self):
        app = editor()
        async with app.run_test() as pilot:
            await pilot.press("escape")
            await pilot.pause()

        assert app.result.saved is False
        assert app.result.text == "existing text"

    async def test_unsaved_changes_need_a_second_press(self):
        app = editor()
        async with app.run_test() as pilot:
            await pilot.press(*"more")
            await pilot.press("escape")
            await pilot.pause()

            assert app.result is None, "first press must not decide anything"
            status = app.query_one("#status")
            assert "Unsaved changes" in str(status.render())
            assert "confirm" in status.classes

            await pilot.press("escape")
            await pilot.pause()

        assert app.result.saved is False

    async def test_ctrl_q_shares_the_pending_confirmation_with_escape(self):
        app = editor()
        async with app.run_test() as pilot:
            await pilot.press(*"more")
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert app.result is None

            # Mixed presses count: the pending confirmation is shared, not per-key.
            await pilot.press("escape")
            await pilot.pause()

        assert app.result.saved is False

    async def test_typing_cancels_a_pending_discard(self):
        app = editor()
        async with app.run_test() as pilot:
            await pilot.press(*"more")
            await pilot.press("escape")
            await pilot.pause()

            await pilot.press("x")
            await pilot.pause()
            status = app.query_one("#status")
            assert "confirm" not in status.classes

            # A single escape must prompt again rather than exit.
            await pilot.press("escape")
            await pilot.pause()
            assert app.result is None


class TestTextIsNeverDestroyed:
    """The guarantee that replaces journ's `self.result = None`. quire hands the text back
    unconditionally; whether to persist it -- and in journ's case, encrypted -- is the
    host's decision, but it never has to ask for the text."""

    async def test_confirmed_discard_still_returns_the_edited_text(self):
        app = editor()
        async with app.run_test() as pilot:
            await pilot.press(*" and more")
            await pilot.press("escape")
            await pilot.press("escape")
            await pilot.pause()

        assert app.result.saved is False
        assert app.result.text == "existing text and more"

    async def test_discarding_an_untouched_editor_returns_the_original(self):
        app = editor("original")
        async with app.run_test() as pilot:
            await pilot.press("escape")
            await pilot.pause()

        assert app.result.text == "original"


class TestFooter:
    async def test_footer_tracks_the_live_word_count(self):
        app = editor("one two")
        async with app.run_test() as pilot:
            assert "2 words" in str(app.query_one("#status").render())

            await pilot.press(*" three")
            await pilot.pause()
            assert "3 words" in str(app.query_one("#status").render())

    async def test_emphasis_is_applied_when_the_host_asks_for_it(self):
        def footer(word_count: int) -> FooterText:
            return FooterText(text=f"{word_count} words", emphasis=word_count >= 2)

        app = editor("", footer=footer)
        async with app.run_test() as pilot:
            assert "emphasis" not in app.query_one("#status").classes

            await pilot.press(*"hi there")
            await pilot.pause()
            assert "emphasis" in app.query_one("#status").classes


class TestExtraBindings:
    async def test_host_binding_fires_its_action(self):
        pressed = []
        binding = ExtraBinding(key="ctrl+t", description="Toggle", action=lambda: pressed.append(1))

        app = editor(extra_bindings=[binding])
        async with app.run_test() as pilot:
            await pilot.press("ctrl+t")
            await pilot.pause()

        assert pressed == [1]

    async def test_host_binding_refreshes_the_footer_with_new_host_state(self):
        """The host's footer closes over its own mutable state, so quire has to re-render
        after dispatching or a toggle would fire invisibly."""
        state = {"label": "off"}
        binding = ExtraBinding(
            key="ctrl+t", description="Toggle", action=lambda: state.update(label="on")
        )

        def footer(word_count: int) -> FooterText:
            return FooterText(text=f"{state['label']} | {word_count} words")

        app = editor(footer=footer, extra_bindings=[binding])
        async with app.run_test() as pilot:
            assert "off |" in str(app.query_one("#status").render())

            await pilot.press("ctrl+t")
            await pilot.pause()
            assert "on |" in str(app.query_one("#status").render())

    async def test_host_binding_cancels_a_pending_discard(self):
        binding = ExtraBinding(key="ctrl+t", description="Toggle", action=lambda: None)

        app = editor(extra_bindings=[binding])
        async with app.run_test() as pilot:
            await pilot.press(*"more")
            await pilot.press("escape")
            await pilot.pause()
            assert "confirm" in app.query_one("#status").classes

            await pilot.press("ctrl+t")
            await pilot.pause()
            assert "confirm" not in app.query_one("#status").classes

            # Still one press away from exiting, not two.
            await pilot.press("escape")
            await pilot.pause()
            assert app.result is None

    async def test_several_host_bindings_dispatch_independently(self):
        fired = []
        app = editor(
            extra_bindings=[
                ExtraBinding("ctrl+t", "First", lambda: fired.append("first")),
                ExtraBinding("ctrl+g", "Second", lambda: fired.append("second")),
            ]
        )
        async with app.run_test() as pilot:
            await pilot.press("ctrl+g")
            await pilot.press("ctrl+t")
            await pilot.pause()

        assert fired == ["second", "first"]
