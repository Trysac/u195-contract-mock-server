"""contract_mock_server - Mock HTTP server from consumer contract files."""

from __future__ import annotations

import logging

from .core import (
    Contract,
    ContractError,
    ContractErrorCode,
    Interaction,
    LogEntry,
    MockEngine,
    Request,
    Response,
    Server,
    load_contract,
    serve,
)

__all__ = [
    "Contract",
    "ContractError",
    "ContractErrorCode",
    "Interaction",
    "LogEntry",
    "MockEngine",
    "Request",
    "Response",
    "Server",
    "__version__",
    "load_contract",
    "serve",
]

__version__ = "0.1.0"

logging.getLogger(__name__).addHandler(logging.NullHandler())
