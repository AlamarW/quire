from datetime import timedelta

from quire.words import count_words, format_elapsed, words_per_minute


def test_count_words():
    assert count_words("one two three") == 3
    assert count_words("") == 0
    assert count_words("   spaced   out   ") == 2


def test_words_per_minute():
    assert words_per_minute(120, timedelta(minutes=2)) == 60.0


def test_words_per_minute_zero_elapsed_time_does_not_divide_by_zero():
    assert words_per_minute(50, timedelta(seconds=0)) == 0.0


def test_format_elapsed():
    assert format_elapsed(timedelta(hours=1, minutes=2, seconds=3)) == (
        "1 hour(s), 2 minute(s), and 3 seconds"
    )


def test_format_elapsed_over_a_day():
    assert format_elapsed(timedelta(days=1, hours=1)) == "25 hour(s), 0 minute(s), and 0 seconds"
