"""Unit tests for codexd.harness.rooms.parse_room_meta.

`parse_room_meta` is on the public stability surface (see
docs/api-stability.md); cover its behavior directly so the gate doesn't
rely on culture's integration tests for shared-tier coverage.
"""

from __future__ import annotations

from codexd.harness.rooms import parse_room_meta


def test_empty_input_returns_empty_dict():
    assert parse_room_meta("") == {}


def test_single_key_value_pair():
    assert parse_room_meta("topic=hello") == {"topic": "hello"}


def test_multiple_key_value_pairs():
    assert parse_room_meta("a=1;b=2;c=3") == {"a": "1", "b": "2", "c": "3"}


def test_strips_whitespace_around_keys_and_values():
    assert parse_room_meta(" a = 1 ; b = 2 ") == {"a": "1", "b": "2"}


def test_skips_pairs_without_equals():
    assert parse_room_meta("a=1;justakey;b=2") == {"a": "1", "b": "2"}


def test_instructions_captured_verbatim_including_semicolons():
    text = "topic=hi;instructions=do A; then B; finally C"
    out = parse_room_meta(text)
    assert out == {
        "topic": "hi",
        "instructions": "do A; then B; finally C",
    }


def test_instructions_only():
    assert parse_room_meta("instructions=multi;line;text") == {
        "instructions": "multi;line;text",
    }


def test_instructions_trailing_semicolon_before_is_stripped():
    text = "topic=t;;instructions=body"
    assert parse_room_meta(text) == {"topic": "t", "instructions": "body"}


def test_value_with_equals_sign_keeps_remainder():
    assert parse_room_meta("expr=a=b=c") == {"expr": "a=b=c"}
