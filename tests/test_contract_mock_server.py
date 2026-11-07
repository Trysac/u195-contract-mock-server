"""Behavior tests for the public API of contract_mock_server."""

from __future__ import annotations

import pytest

import contract_mock_server


def test_normalize_trims_and_lowercases() -> None:
    assert contract_mock_server.normalize("  Hello World ") == "hello world"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_normalize_rejects_blank_input(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        contract_mock_server.normalize(value)


def test_version_is_semver() -> None:
    parts = contract_mock_server.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
