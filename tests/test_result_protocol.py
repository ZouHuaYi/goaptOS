from gtos.core.interfaces.result import append_log, extract_error_message, normalize_error


def test_append_log_writes_structured_log_list() -> None:
    out = append_log({"success": True}, "info", "unit.event", "message", sample=1)
    assert "_logs" in out
    assert len(out["_logs"]) == 1
    assert out["_logs"][0]["event"] == "unit.event"
    assert out["_logs"][0]["data"]["sample"] == 1


def test_normalize_error_and_extract_message() -> None:
    err = normalize_error("boom", default_code="unit_error", retriable=True)
    result = {"success": False, "_error": err}
    assert err["code"] == "unit_error"
    assert err["retriable"] is True
    assert extract_error_message(result) == "boom"
