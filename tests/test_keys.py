import pytest

from terminal_linux.actions import _normalize_key, parse_chord, parse_keys
from terminal_linux.errors import SessionError


def test_mac_aliases():
    assert _normalize_key("cmd") == "ctrl"
    assert _normalize_key("return") == "Return"
    assert _normalize_key("esc") == "Escape"


@pytest.mark.parametrize(
    ("spec", "chord"),
    [
        ("ctrl+c", "ctrl+c"),
        ("Ctrl+Shift+T", "ctrl+shift+T"),
        ("cmd+space", "ctrl+space"),
        ("alt+F4", "alt+F4"),
        ("alt+f4", "alt+F4"),
        ("f5", "F5"),
        ("pgdn", "Page_Down"),
        ("enter", "Return"),
        # Regression: the key after the last '+' used to be lost.
        ("ctrl++", "ctrl+plus"),
        ("+", "plus"),
        ("ctrl+-", "ctrl+minus"),
        # Regression: a lone modifier used to fail with "no key in specification".
        ("super", "Super_L"),
        ("ctrl+shift", "ctrl+Shift_L"),
        ("win+d", "super+d"),
    ],
)
def test_parse_chord(spec, chord):
    assert parse_chord(spec) == chord


def test_parse_keys_sequence():
    assert parse_keys("ctrl+a ctrl+c") == ["ctrl+a", "ctrl+c"]


@pytest.mark.parametrize("spec", ["", "   ", "a+b", "ctrl+a+b"])
def test_bad_keyspec_is_bad_args(spec):
    with pytest.raises(SessionError) as err:
        parse_keys(spec)
    assert err.value.code == "bad_args"
