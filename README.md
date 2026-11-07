# contract-mock-server

[![PyPI version](https://img.shields.io/pypi/v/trysac-contract-mock-server)](https://pypi.org/project/trysac-contract-mock-server/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-contract-mock-server)](LICENSE)
[![CI](https://github.com/Trysac/u195-contract-mock-server/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u195-contract-mock-server/actions/workflows/ci.yml)

Mock HTTP server from consumer contract files: request matching with path templates, query, headers and JSON subset bodies, mismatch reports and unused checks

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-contract-mock-server
# or
uv add trysac-contract-mock-server
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import contract_mock_server

# normalize() trims surrounding whitespace and lower-cases the text.
print(contract_mock_server.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    contract_mock_server.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
