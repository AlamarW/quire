"""Word count / words-per-minute helpers, extracted so they're independently testable."""

from __future__ import annotations

from datetime import timedelta


def count_words(text: str) -> int:
    return len(text.split())


def words_per_minute(word_count: int, elapsed: timedelta) -> float:
    minutes = elapsed.total_seconds() / 60
    if minutes <= 0:
        return 0.0
    return round(word_count / minutes, 1)


def format_elapsed(elapsed: timedelta) -> str:
    total_seconds = int(elapsed.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours} hour(s), {minutes} minute(s), and {seconds} seconds"
