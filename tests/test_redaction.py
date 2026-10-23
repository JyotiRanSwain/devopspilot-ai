from app.core.redaction import MASK, redact, redact_env


def test_redacts_common_secret_shapes():
    cases = [
        "Authorization: Bearer abcdef1234567890", "password=hunter2", '"api_key": "abc123"',
        "AKIAABCDEFGHIJKLMNOP", "postgres://user:pa55w0rd@db:5432/x", "token: ghp_" + "a" * 30,
        "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4", "sk-" + "a" * 30,
    ]
    for text in cases:
        out = redact(text)
        assert MASK in out, text
    assert "hunter2" not in redact("password=hunter2") and "pa55w0rd" not in redact(cases[4])


def test_keeps_non_secret_text():
    assert redact("GET /health 200 in 3ms") == "GET /health 200 in 3ms"


def test_redact_env_masks_by_name():
    out = {e["name"]: e["value"] for e in redact_env(["DB_PASSWORD=x", "MODE=prod", "URL=mysql://u:p@h/db"])}
    assert out["DB_PASSWORD"] == MASK and out["MODE"] == "prod" and "p@" not in out["URL"]
