# quire

A *quire* is a gathering of folded sheets bound together into a book. This one is the
shared foundation under [journ](https://github.com/AlamarW/journ) and stet: the parts of a
terminal writing tool that aren't about what you're writing -- resolving your editor,
running a built-in one, storing text, and keeping revisions of it.

## Why it exists

stet was built by porting journ's architecture, and the copies drifted. The clearest case:
both apps have a built-in editor where a mistyped <kbd>Ctrl+Q</kbd> takes a second
confirming press before discarding unsaved work -- a guard added after one actually cost a
600-word session. stet also keeps a recovery copy of the discarded text. journ, which got
the same guard backported, does not; it drops the text on the floor. Same feature, two
implementations, and the weaker one lives in the app holding the journal.

quire is where that stops being possible.

## Design rules

1. **Composition over flags.** quire never branches on which app is calling. Variation is
   injected -- callbacks, subclasses, codecs. journ's editor footer isn't "goal display
   on/off", it's a *different footer*, and a boolean would put a chain of `if`s in here.
2. **Presence is fine, shape is not.** Apps import the modules they want. That's
   packaging, not configuration.
3. **Nothing enters quire without two real consumers.** journ's streaks and stet's
   statuses stay in their own apps. Flags would make it feel safe to break this rule;
   injection can't.
4. **Guards are never optional.** quire always returns discarded text and always stashes
   it. The recovery directory is a path, not a feature toggle.
5. **quire stores opaque content.** journ encrypts its entries; a revision table full of
   plaintext prior versions would silently void that. quire takes a codec and never learns
   whether it was handed prose or ciphertext.

## What's here

| Module | What it does |
| --- | --- |
| `quire.config` | `$EDITOR` resolution, saved choices, the interactive picker, argv splitting |
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
