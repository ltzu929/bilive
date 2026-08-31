from src.blrec_danmu_fix import _has_cookie_field, sign_wbi_params


def test_has_cookie_field_handles_cookie_boundaries_case_insensitively():
    cookie = "SESSDATA=secret; BuViD3=browser-id; bili_jct=csrf"

    assert _has_cookie_field(cookie, "buvid3")
    assert not _has_cookie_field(cookie, "buvid4")


def test_sign_wbi_params_is_deterministic_and_filters_values():
    signed = sign_wbi_params(
        {"id": 8792912, "type": 0, "unsafe": "a!'()*b"},
        "0123456789abcdef0123456789abcdef",
        "fedcba9876543210fedcba9876543210",
        now=1700000000,
    )

    assert signed["wts"] == "1700000000"
    assert signed["unsafe"] == "ab"
    assert len(signed["w_rid"]) == 32
    assert signed == sign_wbi_params(
        {"id": 8792912, "type": 0, "unsafe": "a!'()*b"},
        "0123456789abcdef0123456789abcdef",
        "fedcba9876543210fedcba9876543210",
        now=1700000000,
    )
