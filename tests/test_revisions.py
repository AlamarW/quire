"""What quire guarantees about revisions: that a prior version survives being overwritten,
that a session of edits leaves one entry rather than one per save, that reverting is itself
recoverable, and that a host encrypting its content does not end up with a table of
plaintext copies of it."""

import base64
import sqlite3
from datetime import datetime, timedelta

import pytest

from quire.revisions import (
    AGENT,
    HUMAN,
    PlainTextCodec,
    Revision,
    RevisionStore,
    RevisionTarget,
    UnknownCodec,
)

ESSAY = RevisionTarget("essay", 12, "content")
ENTRY = RevisionTarget("entry", "2026-07-30", "text")

START = datetime(2026, 7, 30, 9, 0)


def at(minutes: int) -> datetime:
    return START + timedelta(minutes=minutes)


class ReversingCodec:
    """Stands in for journ's Fernet codec: enough not to be text, cheap enough to assert on.
    Reversal alone would leave words findable, so it also base64s -- the point of the tests
    below is that nothing recognisable reaches the file."""

    name = "reversed"

    def encode(self, text: str) -> bytes:
        return base64.b64encode(text[::-1].encode("utf-8"))

    def decode(self, blob: bytes) -> str:
        return base64.b64decode(blob).decode("utf-8")[::-1]


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def store(conn):
    return RevisionStore(conn)


class TestRecording:
    def test_a_prior_version_survives_being_overwritten(self, store):
        store.record(ESSAY, "the first draft", now=at(0))

        assert [r.text for r in store.history(ESSAY)] == ["the first draft"]

    def test_history_is_newest_first(self, store):
        store.record(ESSAY, "one", now=at(0))
        store.record(ESSAY, "two", now=at(60))
        store.record(ESSAY, "three", now=at(120))

        assert [r.text for r in store.history(ESSAY)] == ["three", "two", "one"]

    def test_targets_do_not_see_each_others_history(self, store):
        store.record(ESSAY, "an essay", now=at(0))
        store.record(ENTRY, "an entry", now=at(0))

        assert [r.text for r in store.history(ESSAY)] == ["an essay"]
        assert [r.text for r in store.history(ENTRY)] == ["an entry"]

    def test_the_same_record_id_under_different_kinds_stays_separate(self, store):
        store.record(RevisionTarget("essay", 1), "essay text", now=at(0))
        store.record(RevisionTarget("note", 1), "note text", now=at(0))

        assert store.count(RevisionTarget("essay", 1)) == 1
        assert store.count(RevisionTarget("note", 1)) == 1

    def test_fields_of_one_record_stay_separate(self, store):
        store.record(RevisionTarget("essay", 1, "content"), "body", now=at(0))
        store.record(RevisionTarget("essay", 1, "summary"), "abstract", now=at(0))

        assert [r.text for r in store.history(RevisionTarget("essay", 1, "summary"))] == [
            "abstract"
        ]

    def test_an_integer_id_and_its_string_form_are_one_target(self, store):
        """stet passes an int, and anything round-tripping through the row comes back text."""
        store.record(RevisionTarget("essay", 12), "text", now=at(0))

        assert store.count(RevisionTarget("essay", "12")) == 1

    def test_the_returned_revision_carries_the_target_it_was_given(self, store):
        revision = store.record(ESSAY, "text", actor=AGENT, now=at(0))

        assert revision == Revision(
            id=revision.id, target=ESSAY, text="text", actor=AGENT, created_at=at(0)
        )

    def test_empty_text_is_still_a_revision(self, store):
        """Clearing a field is exactly the edit you most want to be able to undo."""
        store.record(ESSAY, "", now=at(0))

        assert store.count(ESSAY) == 1


class TestCoalescing:
    def test_a_second_save_in_the_same_session_does_not_add_an_entry(self, store):
        store.record(ESSAY, "first", now=at(0))
        assert store.record(ESSAY, "second", now=at(5)) is None

        assert [r.text for r in store.history(ESSAY)] == ["first"]

    def test_the_kept_version_is_the_oldest_in_the_window(self, store):
        """Coalescing has to keep the state the session started from -- keeping the newest
        would make a session's own history the one thing it cannot recover."""
        store.record(ESSAY, "as it was this morning", now=at(0))
        store.record(ESSAY, "halfway through", now=at(10))
        store.record(ESSAY, "nearly done", now=at(20))

        assert [r.text for r in store.history(ESSAY)] == ["as it was this morning"]

    def test_a_later_session_records_again(self, store):
        store.record(ESSAY, "morning", now=at(0))
        store.record(ESSAY, "afternoon", now=at(31))

        assert [r.text for r in store.history(ESSAY)] == ["afternoon", "morning"]

    def test_the_window_is_measured_from_the_kept_revision_not_the_last_edit(self, store):
        """Otherwise saving every few minutes for hours would chain the window forward and
        leave a single revision covering the whole day."""
        store.record(ESSAY, "kept", now=at(0))
        for minute in range(5, 30, 5):
            store.record(ESSAY, f"at {minute}", now=at(minute))

        store.record(ESSAY, "past the window", now=at(31))

        assert [r.text for r in store.history(ESSAY)] == ["past the window", "kept"]

    def test_a_different_actor_is_never_coalesced_away(self, store):
        """An agent's rewrite is the edit you most want to see attributed, so it must not
        disappear into a revision recorded by the human a minute earlier."""
        store.record(ESSAY, "what I wrote", actor=HUMAN, now=at(0))
        store.record(ESSAY, "what the model rewrote", actor=AGENT, now=at(1))

        assert [(r.text, r.actor) for r in store.history(ESSAY)] == [
            ("what the model rewrote", AGENT),
            ("what I wrote", HUMAN),
        ]

    def test_coalescing_is_per_target(self, store):
        store.record(ESSAY, "essay", now=at(0))
        store.record(ENTRY, "entry", now=at(1))

        assert store.count(ESSAY) == 1
        assert store.count(ENTRY) == 1

    def test_the_window_is_configurable(self, conn):
        store = RevisionStore(conn, coalesce_window=timedelta(minutes=1))
        store.record(ESSAY, "first", now=at(0))
        store.record(ESSAY, "second", now=at(2))

        assert store.count(ESSAY) == 2

    def test_a_clock_moving_backwards_records_rather_than_drops(self, store):
        """DST and NTP corrections both do this. An extra revision is a harmless outcome;
        a silently missing one is not."""
        store.record(ESSAY, "first", now=at(60))
        store.record(ESSAY, "after the clock went back", now=at(0))

        assert store.count(ESSAY) == 2

    def test_checkpoint_ignores_the_window(self, store):
        store.record(ESSAY, "first", now=at(0))
        store.checkpoint(ESSAY, "second", now=at(1))

        assert [r.text for r in store.history(ESSAY)] == ["second", "first"]


class TestRevert:
    def test_returns_the_historical_text(self, store):
        original = store.record(ESSAY, "the version I liked", now=at(0))
        store.record(ESSAY, "a detour", now=at(60))

        assert store.revert(ESSAY, original.id, "where I am now", now=at(120)) == (
            "the version I liked"
        )

    def test_what_was_reverted_away_from_is_still_recoverable(self, store):
        original = store.record(ESSAY, "the version I liked", now=at(0))
        store.revert(ESSAY, original.id, "the text being thrown away", now=at(60))

        assert "the text being thrown away" in [r.text for r in store.history(ESSAY)]

    def test_a_revert_is_never_coalesced_into_the_edit_before_it(self, store):
        """Reverting seconds after an edit is the normal case -- "no, undo that" -- and it
        is precisely when coalescing would swallow the state needed to undo the undo."""
        original = store.record(ESSAY, "original", now=at(0))
        store.revert(ESSAY, original.id, "the mistake", now=at(1))

        assert [r.text for r in store.history(ESSAY)] == ["the mistake", "original"]

    def test_reverting_twice_returns_to_where_it_started(self, store):
        original = store.record(ESSAY, "original", now=at(0))
        store.revert(ESSAY, original.id, "detour", now=at(60))
        detour = store.latest(ESSAY)

        assert store.revert(ESSAY, detour.id, "original", now=at(120)) == "detour"

    def test_a_revision_from_another_target_is_refused(self, store):
        """Ids are global to the table, so nothing but this check stops one record's text
        being restored over another's."""
        foreign = store.record(ENTRY, "someone else's text", now=at(0))

        with pytest.raises(LookupError):
            store.revert(ESSAY, foreign.id, "current", now=at(1))

    def test_a_refused_revert_records_nothing(self, store):
        foreign = store.record(ENTRY, "someone else's text", now=at(0))

        with pytest.raises(LookupError):
            store.revert(ESSAY, foreign.id, "current", now=at(1))

        assert store.count(ESSAY) == 0

    def test_an_unknown_revision_id_is_refused(self, store):
        with pytest.raises(LookupError):
            store.revert(ESSAY, 999, "current", now=at(0))


class TestOpaqueContent:
    def test_the_stored_bytes_are_what_the_codec_produced(self, conn):
        store = RevisionStore(conn, codecs=[ReversingCodec()])
        store.record(ENTRY, "a private thought", now=at(0))

        stored = conn.execute("SELECT content FROM revision").fetchone()[0]
        assert b"private" not in stored
        assert stored == ReversingCodec().encode("a private thought")

    def test_encoded_text_round_trips(self, conn):
        store = RevisionStore(conn, codecs=[ReversingCodec()])
        store.record(ENTRY, "a private thought", now=at(0))

        assert store.history(ENTRY)[0].text == "a private thought"

    def test_nothing_recognisable_reaches_the_database_file(self, tmp_path):
        """The check the plan calls for on journ's real database, run here where it can be
        automated: open the file as bytes and look for the words that were written."""
        path = tmp_path / "journal.db"
        conn = sqlite3.connect(path)
        try:
            store = RevisionStore(conn, codecs=[ReversingCodec()])
            store.record(ENTRY, "the secret sentence", now=at(0))
            conn.commit()
        finally:
            conn.close()

        assert b"secret" not in path.read_bytes()

    def test_plaintext_history_stays_readable_after_a_codec_is_added(self, conn):
        """journ setting a passphrase must not orphan the revisions it wrote before it had
        one, which is why the codec's name is stored per row rather than per store."""
        RevisionStore(conn, codecs=[PlainTextCodec()]).record(
            ENTRY, "written in the clear", now=at(0)
        )

        encrypted = RevisionStore(conn, codecs=[ReversingCodec(), PlainTextCodec()])
        encrypted.record(ENTRY, "written after the passphrase", now=at(60))

        assert [r.text for r in encrypted.history(ENTRY)] == [
            "written after the passphrase",
            "written in the clear",
        ]

    def test_new_revisions_use_the_first_codec(self, conn):
        store = RevisionStore(conn, codecs=[ReversingCodec(), PlainTextCodec()])
        store.record(ENTRY, "a private thought", now=at(0))

        assert conn.execute("SELECT codec FROM revision").fetchone()[0] == "reversed"

    def test_unreadable_history_raises_rather_than_returning_ciphertext(self, conn):
        RevisionStore(conn, codecs=[ReversingCodec()]).record(ENTRY, "encrypted", now=at(0))

        locked = RevisionStore(conn, codecs=[PlainTextCodec()])
        with pytest.raises(UnknownCodec):
            locked.history(ENTRY)

    def test_counting_works_without_being_able_to_decode(self, conn):
        """So a locked journ can still say how many revisions an entry has."""
        RevisionStore(conn, codecs=[ReversingCodec()]).record(ENTRY, "encrypted", now=at(0))

        assert RevisionStore(conn, codecs=[PlainTextCodec()]).count(ENTRY) == 1

    def test_a_store_needs_a_codec_to_write_with(self, conn):
        with pytest.raises(ValueError):
            RevisionStore(conn, codecs=[])


class TestPersistence:
    def test_the_table_is_created_on_demand(self, conn):
        RevisionStore(conn)

        tables = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        assert ("revision",) in tables

    def test_opening_a_second_store_on_the_same_connection_is_safe(self, conn):
        RevisionStore(conn).record(ESSAY, "text", now=at(0))

        assert RevisionStore(conn).count(ESSAY) == 1

    def test_history_survives_reopening_the_database(self, tmp_path):
        path = tmp_path / "stet.db"
        conn = sqlite3.connect(path)
        RevisionStore(conn).record(ESSAY, "text", now=at(0))
        conn.commit()
        conn.close()

        reopened = sqlite3.connect(path)
        try:
            assert [r.text for r in RevisionStore(reopened).history(ESSAY)] == ["text"]
        finally:
            reopened.close()

    def test_created_at_round_trips_as_a_datetime(self, store):
        store.record(ESSAY, "text", now=at(0))

        assert store.history(ESSAY)[0].created_at == at(0)

    def test_forget_drops_a_deleted_records_history(self, store):
        store.record(ESSAY, "text", now=at(0))
        store.record(ENTRY, "other", now=at(0))

        store.forget(ESSAY)

        assert store.count(ESSAY) == 0
        assert store.count(ENTRY) == 1

    def test_history_of_an_unknown_target_is_empty(self, store):
        assert store.history(RevisionTarget("essay", 999)) == []
        assert store.latest(RevisionTarget("essay", 999)) is None

    def test_get_returns_none_for_an_unknown_id(self, store):
        assert store.get(999) is None
