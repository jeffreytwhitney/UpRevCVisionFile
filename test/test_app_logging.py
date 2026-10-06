import logging

import pytest

from app_logging import _resolve_log_level


@pytest.mark.parametrize(
    ("level_name", "expected"),
    [
        ("DEBUG", logging.DEBUG),
        ("info", logging.INFO),
        (" warning ", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("CRITICAL", logging.CRITICAL),
    ],
)
def test_resolve_log_level_reads_environment(monkeypatch, level_name, expected):
    monkeypatch.setenv("LOG_LEVEL", level_name)

    assert _resolve_log_level(logging.getLogger("test")) == expected


def test_resolve_log_level_defaults_to_debug(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    assert _resolve_log_level(logging.getLogger("test")) == logging.DEBUG


def test_resolve_log_level_warns_and_defaults_for_invalid_value(monkeypatch, caplog):
    monkeypatch.setenv("LOG_LEVEL", "verbose")

    with caplog.at_level(logging.WARNING):
        level = _resolve_log_level(logging.getLogger("test"))

    assert level == logging.DEBUG
    assert "Invalid LOG_LEVEL 'VERBOSE'; using DEBUG" in caplog.text
