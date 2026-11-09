from terminal_linux.viewer import _csi_params, _tab_strip


def test_tab_strip_marks_active():
    assert _tab_strip("work", ["demo", "work", "lab"]) == "1:demo [2:work] 3:lab"


def test_csi_alt_arrows():
    params, final = _csi_params(b"\033[1;3D")
    assert params == [1, 3]
    assert final == ord("D")
    params, final = _csi_params(b"\033[1;3C")
    assert params == [1, 3]
    assert final == ord("C")
