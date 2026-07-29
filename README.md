# quire

A *quire* is a gathering of folded sheets bound together into a book. This one is the
shared foundation under [journ](https://github.com/AlamarW/journ) and stet: the parts of a
terminal writing tool that aren't about what you're writing -- resolving your editor,
running a built-in one, storing text, and keeping revisions of it.

## Why it exists

stet was built by porting journ's architecture, and the copies drifted. Both apps grew a
built-in editor where a mistyped <kbd>Ctrl+Q</kbd> takes a second confirming press before
discarding unsaved work -- a guard added after one actually cost a real 600-word session --
and each maintained its own copy of it.

They also diverged on what happens next. stet keeps a recovery copy of discarded text;
journ throws it away, deliberately, because journ encrypts its entries and promises they
never touch disk in plaintext. That asymmetry is defensible. Maintaining the guard twice is
not, and journ losing the text outright is a worse answer than journ stashing it encrypted.

quire is where the guard stops being duplicated, and where the difference between the two
apps becomes a decision the host makes rather than a fork in the implementation.

## Design rules

1. **Composition over flags.** quire never branches on which app is calling. Variation is
   injected -- callbacks, subclasses, codecs. journ's editor footer isn't "goal display
   on/off", it's a *different footer*, and a boolean would put a chain of `if`s in here.
2. **Presence is fine, shape is not.** Apps import the modules they want. That's
   packaging, not configuration.
3. **Nothing enters quire without two real consumers.** journ's streaks and stet's
   statuses stay in their own apps. Flags would make it feel safe to break this rule;
   injection can't.
4. **Guards are never optional.** quire always hands discarded text back to the caller;
   there is no code path that destroys it. What the host then does with it *is* the host's
   call -- journ has to encrypt what stet can write in plaintext -- but no host has to ask
   for the text, and none can opt out of receiving it.
5. **quire stores opaque content.** journ encrypts its entries; a revision table full of
   plaintext prior versions would silently void that. quire takes a codec and never learns
   whether it was handed prose or ciphertext.

## What's here

| Module | What it does |
| --- | --- |
| `quire.config` | `$EDITOR` resolution, saved choices, the interactive picker, argv splitting |
| `quire.editor` | The built-in Textual editor: layout, save/discard keys, the discard guard |
| `quire.words` | Word counting, words-per-minute, elapsed formatting |
| `quire.terminal` | Cross-platform `clear_screen` |

`quire.config` takes an `EditorEnvironment` carrying the host's name, paths, and command
formatter. Build it at call time rather than import time -- both apps keep module-level
path globals their tests monkeypatch, and an environment captured at import would pin the
real `~/.journ` or `~/.stet` before the patch lands.

## Installation

quire is consumed as a git dependency, not from PyPI:

```sh
uv add git+https://github.com/AlamarW/quire --tag v0.1.0
```

For local development against an unreleased quire, override the source in the consuming
app's `pyproject.toml`:

```toml
[tool.uv.sources]
quire = { path = "../quire", editable = true }
```

## Development

```sh
uv sync
uv run pytest
uv run ruff check .
```
