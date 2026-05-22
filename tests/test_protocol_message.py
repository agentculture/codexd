"""Unit tests for ``codexd.protocol.message`` — IRC line parse/format."""

from __future__ import annotations

import pytest

from codexd.protocol.message import (
    Message,
    _escape_tag_value,
    _unescape_tag_value,
)

# ── tag value escape / unescape ──────────────────────────────────────


@pytest.mark.parametrize(
    "raw,decoded",
    [
        (r"a\:b", "a;b"),
        (r"a\sb", "a b"),
        (r"a\\b", r"a\b"),
        (r"a\rb", "a\rb"),
        (r"a\nb", "a\nb"),
        ("no-escapes", "no-escapes"),
    ],
)
def test_unescape_known_sequences(raw: str, decoded: str) -> None:
    assert _unescape_tag_value(raw) == decoded


def test_unescape_unknown_sequence_drops_backslash() -> None:
    """Per IRCv3 spec, unknown escapes yield only the second character."""
    assert _unescape_tag_value(r"\q") == "q"


def test_unescape_trailing_backslash_kept() -> None:
    """A bare trailing backslash is kept verbatim (no second char to read)."""
    assert _unescape_tag_value("trailing\\") == "trailing\\"


@pytest.mark.parametrize(
    "decoded,encoded",
    [
        ("a;b", r"a\:b"),
        ("a b", r"a\sb"),
        ("a\\b", r"a\\b"),
        ("a\rb", r"a\rb"),
        ("a\nb", r"a\nb"),
    ],
)
def test_escape_round_trip(decoded: str, encoded: str) -> None:
    assert _escape_tag_value(decoded) == encoded
    assert _unescape_tag_value(encoded) == decoded


# ── Message.parse ────────────────────────────────────────────────────


def test_parse_simple_privmsg() -> None:
    msg = Message.parse("PRIVMSG #channel :hello world\r\n")
    assert msg.command == "PRIVMSG"
    assert msg.params == ["#channel", "hello world"]
    assert msg.prefix is None
    assert msg.tags == {}


def test_parse_with_prefix() -> None:
    msg = Message.parse(":nick!user@host PING server\r\n")
    assert msg.prefix == "nick!user@host"
    assert msg.command == "PING"
    assert msg.params == ["server"]


def test_parse_with_tags() -> None:
    msg = Message.parse("@k1=v1;k2=v\\s2;flag PRIVMSG #c :hi\r\n")
    assert msg.tags == {"k1": "v1", "k2": "v 2", "flag": ""}
    assert msg.command == "PRIVMSG"


def test_parse_command_uppercased() -> None:
    assert Message.parse("privmsg #c :hi").command == "PRIVMSG"


def test_parse_strips_crlf() -> None:
    assert Message.parse("PING server\r\n").command == "PING"
    assert Message.parse("PING server\n").command == "PING"
    assert Message.parse("PING server").command == "PING"


def test_parse_empty_after_only_tags() -> None:
    """A wire line containing only an @-tag block is malformed."""
    msg = Message.parse("@only-tags")
    assert msg.tags == {}
    assert msg.command == ""


def test_parse_only_at_then_space() -> None:
    """``@tags `` with empty command after tags."""
    msg = Message.parse("@k=v ")
    # Tags parsed, but the remaining ``""`` is empty so command is "".
    assert msg.tags == {"k": "v"}
    assert msg.command == ""


def test_parse_prefix_only_then_eof() -> None:
    """``:prefix`` with no command — return empty message."""
    msg = Message.parse(":nick!user")
    assert msg.prefix is None
    assert msg.command == ""


def test_parse_no_command_after_split() -> None:
    """Pure whitespace should return command='' rather than crashing."""
    msg = Message.parse("    ")
    assert msg.command == ""


def test_parse_tag_block_no_space_after() -> None:
    """``@tags`` without a trailing space is malformed (no command)."""
    msg = Message.parse("@k=v")
    assert msg.tags == {}
    assert msg.command == ""


def test_parse_trailing_with_spaces() -> None:
    """The ` :` trailing param swallows the rest of the line as one arg."""
    msg = Message.parse("PRIVMSG #c :hello there friend")
    assert msg.params == ["#c", "hello there friend"]


def test_parse_empty_tag_pieces() -> None:
    """Empty pieces in a tag block (``;;``) are skipped."""
    msg = Message.parse("@k1=v;;k2=w PRIVMSG #c :hi")
    assert msg.tags == {"k1": "v", "k2": "w"}


# ── Message.format ───────────────────────────────────────────────────


def test_format_simple_privmsg() -> None:
    msg = Message(command="PRIVMSG", params=["#c", "hello world"])
    assert msg.format() == "PRIVMSG #c :hello world\r\n"


def test_format_with_prefix() -> None:
    msg = Message(prefix="nick!u@h", command="PING", params=["server"])
    assert msg.format() == ":nick!u@h PING server\r\n"


def test_format_with_tags() -> None:
    msg = Message(tags={"flag": "", "k": "v 1"}, command="PRIVMSG", params=["#c", "hi"])
    formatted = msg.format()
    # Last param "hi" has no space / colon-prefix / emptyness, so it is
    # serialized inline (no trailing ``:`` marker).
    assert formatted == r"@flag;k=v\s1 PRIVMSG #c hi" + "\r\n"


def test_format_last_param_starts_with_colon_gets_trailing() -> None:
    msg = Message(command="NOTE", params=[":already-colon"])
    assert msg.format() == "NOTE ::already-colon\r\n"


def test_format_empty_last_param_gets_trailing() -> None:
    msg = Message(command="NOTE", params=[""])
    assert msg.format() == "NOTE :\r\n"


def test_format_round_trip() -> None:
    original = "@id=42 :nick!u@h PRIVMSG #c :hello world\r\n"
    msg = Message.parse(original)
    assert msg.format() == original
