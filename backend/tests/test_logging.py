import logging

from app.core.logging import JsonFormatter


def test_json_formatter_never_serializes_exception_message() -> None:
    secret_like_value = "Bearer private-token-value"
    record = logging.LogRecord(
        name="kyra",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="unhandled_request_error",
        args=(),
        exc_info=None,
    )
    record.error_type = "RuntimeError"
    record.error_message = secret_like_value

    formatted = JsonFormatter().format(record)

    assert secret_like_value not in formatted
    assert '"error_type": "RuntimeError"' in formatted
