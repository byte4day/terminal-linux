from terminal_linux.actions import _normalize_key


def test_mac_aliases():
    assert _normalize_key("cmd") == "ctrl"
    assert _normalize_key("return") == "Return"
    assert _normalize_key("esc") == "Escape"
