"""Revision history for text that gets replaced in place.

A host calls `record` with the *outgoing* text just before it overwrites a field. What
accumulates is the sequence of prior versions, newest last, with the live record itself
holding the current one.

Two things are deliberately not quire's business:

*What the content says.* Revisions are stored as bytes through a `Codec`. journ encrypts
its entries, and a revision table full of plaintext prior versions would quietly undo that,
so quire never sees decoded text except when handing it back to the caller that asked.

*What counts as a record.* `RevisionTarget` is `(kind, record_id, field)` with the id
normalized to a string, because journ keys entries by date and stet keys essays by integer.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

HUMAN = "human"
AGENT = "agent"
"""Who made the edit. Recorded for after-the-fact judgement -- "did I write this or did a
model?" is the question you ask when deciding whether to revert -- not as a review gate."""

DEFAULT_COALESCE_WINDOW = timedelta(minutes=30)
"""One writing session should leave one revision, not one per save. Measured from the
retained revision rather than the incoming edit, so a long session cannot chain its way out
of ever recording a second one."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS revision (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    record_id  TEXT NOT NULL,
    field      TEXT NOT NULL,
    content    BLOB NOT NULL,
    codec      TEXT NOT NULL,
    actor      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS revision_target
    ON revision (kind, record_id, field, id);
"""

_COLUMNS = "id, kind, record_id, field, content, codec, actor, created_at"


class Codec(Protocol):
    """How text becomes the bytes quire stores. `name` is written alongside every row so a
    journal that gains a passphrase can still read the revisions it wrote before it had
    one."""

    @property
    def name(self) -> str: ...

    def encode(self, text: str) -> bytes: ...

    def decode(self, blob: bytes) -> str: ...


class PlainTextCodec:
    """The identity codec: UTF-8 in, UTF-8 out. What stet uses, and what journ uses until a
    passphrase is set."""

    name = "plain"

    def encode(self, text: str) -> bytes:
        return text.encode("utf-8")

    def decode(self, blob: bytes) -> str:
        return bytes(blob).decode("utf-8")


@dataclass(frozen=True)
class RevisionTarget:
    """The field whose history is being kept -- `("essay", 12, "content")` and
    `("entry", "2026-07-30", "text")` are the same call."""

    kind: str
    record_id: str
    field: str = "content"

    def __post_init__(self) -> None:
        # journ's ids are dates and stet's are integers; storing both as text means a
        # caller gets back a target equal to the one it passed in either case.
        object.__setattr__(self, "record_id", str(self.record_id))


@dataclass(frozen=True)
class Revision:
    id: int
    target: RevisionTarget
    text: str
    actor: str
    created_at: datetime


class UnknownCodec(LookupError):
    """A revision was written by a codec this store wasn't given -- journ reading encrypted
    history while locked, most likely. Raised rather than returning ciphertext as text."""


@dataclass
class RevisionStore:
    """Revision history over a host's existing connection. The table is created on demand,
    so a host hands over its `sqlite3.Connection` and nothing else.

    `codecs` is ordered: the first writes, and any of them may read. journ passes its Fernet
    codec followed by `PlainTextCodec()` so pre-passphrase history stays readable.
    """

    conn: sqlite3.Connection
    codecs: Sequence[Codec] = field(default_factory=lambda: (PlainTextCodec(),))
    coalesce_window: timedelta = DEFAULT_COALESCE_WINDOW

    def __post_init__(self) -> None:
        if not self.codecs:
            raise ValueError("RevisionStore needs at least one codec to write with")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # --- writing ---

    def record(
        self,
        target: RevisionTarget,
        text: str,
        *,
        actor: str = HUMAN,
        now: datetime | None = None,
    ) -> Revision | None:
        """Keep `text` as a prior version of `target`, unless the same actor already left one
        inside the coalescing window -- in which case the older revision is the more useful
        one to keep, and this returns None.

        Call this with the text being replaced, before replacing it."""
        moment = now or datetime.now()
        latest = self.latest(target)
        if latest is not None and latest.actor == actor:
            # A backwards clock (DST, an NTP correction) makes this negative. Recording an
            # extra revision is the harmless outcome there; treating it as "inside the
            # window" would silently drop one.
            elapsed = moment - latest.created_at
            if timedelta(0) <= elapsed < self.coalesce_window:
                return None
        return self.checkpoint(target, text, actor=actor, now=moment)

    def checkpoint(
        self,
        target: RevisionTarget,
        text: str,
        *,
        actor: str = HUMAN,
        now: datetime | None = None,
    ) -> Revision:
        """Record unconditionally. Used where an edit is a boundary in its own right and
        must not be folded into a neighbour -- a revert being the case that matters, since
        coalescing one away would make the revert itself impossible to undo."""
        moment = now or datetime.now()
        codec = self.codecs[0]
        cursor = self.conn.execute(
            "INSERT INTO revision (kind, record_id, field, content, codec, actor, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                target.kind,
                target.record_id,
                target.field,
                codec.encode(text),
                codec.name,
                actor,
                moment.isoformat(),
            ),
        )
        return Revision(
            id=cursor.lastrowid,
            target=target,
            text=text,
            actor=actor,
            created_at=moment,
        )

    def revert(
        self,
        target: RevisionTarget,
        revision_id: int,
        current_text: str,
        *,
        actor: str = HUMAN,
        now: datetime | None = None,
    ) -> str:
        """Return the text to restore, having first checkpointed `current_text`.

        Reverting is an edit like any other, so it adds to the history rather than truncating
        it -- what you reverted away from stays recoverable. Writing the returned text back to
        the record is the host's job; quire does not own the record."""
        revision = self.get(revision_id)
        if revision is None or revision.target != target:
            raise LookupError(f"revision {revision_id} does not belong to {target}")
        self.checkpoint(target, current_text, actor=actor, now=now)
        return revision.text

    # --- reading ---

    def history(self, target: RevisionTarget, *, limit: int | None = None) -> list[Revision]:
        """Prior versions, newest first."""
        sql = (
            f"SELECT {_COLUMNS} FROM revision WHERE kind = ? AND record_id = ? AND field = ? "
            "ORDER BY id DESC"
        )
        params: list[object] = [target.kind, target.record_id, target.field]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [self._row_to_revision(row) for row in self.conn.execute(sql, params)]

    def latest(self, target: RevisionTarget) -> Revision | None:
        revisions = self.history(target, limit=1)
        return revisions[0] if revisions else None

    def get(self, revision_id: int) -> Revision | None:
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM revision WHERE id = ?", (revision_id,)
        ).fetchone()
        return self._row_to_revision(row) if row else None

    def count(self, target: RevisionTarget) -> int:
        """How many prior versions exist, without decoding any of them -- callable while
        journ is locked, where `history` would raise."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM revision WHERE kind = ? AND record_id = ? AND field = ?",
            (target.kind, target.record_id, target.field),
        ).fetchone()
        return row[0]

    def forget(self, target: RevisionTarget) -> None:
        """Drop a target's history, for when the record itself is deleted. quire has no
        foreign key to cascade from, since it does not know which table the host used."""
        self.conn.execute(
            "DELETE FROM revision WHERE kind = ? AND record_id = ? AND field = ?",
            (target.kind, target.record_id, target.field),
        )

    # --- internals ---

    def _row_to_revision(self, row) -> Revision:
        revision_id, kind, record_id, field_name, content, codec_name, actor, created_at = row
        return Revision(
            id=revision_id,
            target=RevisionTarget(kind=kind, record_id=record_id, field=field_name),
            text=self._codec(codec_name).decode(content),
            actor=actor,
            created_at=datetime.fromisoformat(created_at),
        )

    def _codec(self, name: str) -> Codec:
        for codec in self.codecs:
            if codec.name == name:
                return codec
        raise UnknownCodec(f"no codec named {name!r} is available to read this revision")
