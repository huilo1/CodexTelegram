from codex_telegram.bot import _split_message


def test_split_message_keeps_short_text() -> None:
    assert _split_message("hello") == ["hello"]


def test_split_message_splits_large_text() -> None:
    text = ("a" * 3900) + "\n" + ("b" * 3900)
    chunks = _split_message(text, limit=4000)
    assert len(chunks) == 2
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
