# contract-mock-server

Mock HTTP server from consumer contract files. Solves the problem of frontend and service teams blocking each other due to missing provider APIs and drifting hand-written stubs.

## Installation

```bash
pip install contract-mock-server
```

## Usage

```python
from contract_mock_server import MockEngine, Request, load_contract

contract = load_contract(
    '{"format":"contract-mock/1","interactions":[{"description":"user","request":{"method":"GET","path":"/users/{id}"},"response":{"status":200,"body":{"id":"42","price":1.10}}}]}'
)
engine = MockEngine(contract)
response = engine.handle(Request("GET", "/users/42", {}, {}, b""))
print(response.status, response.body.decode("utf-8"))
```

## API Summary

- `load_contract(text: str, *, max_bytes: int = 5_000_000) -> Contract`: Validates contract string. Raises `ContractError` codes: `input_too_large`, `invalid_contract`, `unsupported_format`, `too_deep`.
- `MockEngine(contract: Contract, *, max_log: int = 1000, max_body_bytes: int = 1_048_576)`: Matching engine.
- `engine.handle(req: Request) -> Response`: Returns a response or 404 with a mismatch report.
- `engine.unused() -> list[str]`: Returns descriptions of unmatched interactions.
- `serve(engine: MockEngine, *, host: str = "127.0.0.1", port: int = 0)`: Context manager running a `ThreadingHTTPServer`.

## Why not Pact?

Pact tooling is heavy. `contract-mock-server` uses a simple, dependency-free JSON format (`contract-mock/1`) and provides a pure matching core that works in any Python environment, including unit tests.

See [docs/SECURITY.md](docs/SECURITY.md) for security information.