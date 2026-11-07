"""CLI entry point for contract_mock_server."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .core import ContractError, MockEngine, load_contract, serve


def main(argv: list[str] | None = None) -> int:
    """Command line interface entrypoint."""
    parser = argparse.ArgumentParser(
        prog="contract-mock-server",
        description="Serve or validate consumer contract mock files.",
    )
    parser.add_argument("--check", metavar="FILE", help="Validate a contract file and exit")
    parser.add_argument("file", nargs="?", help="Contract file to serve")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to (default: 8080)")

    args = parser.parse_args(argv)

    if args.check:
        target = Path(args.check)
        if not target.is_file():
            sys.stderr.write(f"Error: File not found: {args.check}\n")
            return 2
        try:
            content = target.read_text(encoding="utf-8")
            load_contract(content)
            sys.stdout.write(f"Contract {args.check} is valid.\n")
            return 0
        except ContractError as err:
            sys.stderr.write(f"Contract error [{err.code}]: {err.message}\n")
            return 2
        except Exception as err:
            sys.stderr.write(f"Error: {err}\n")
            return 2

    if not args.file:
        parser.print_usage(sys.stderr)
        return 2

    target = Path(args.file)
    if not target.is_file():
        sys.stderr.write(f"Error: File not found: {args.file}\n")
        return 2

    try:
        content = target.read_text(encoding="utf-8")
        contract = load_contract(content)
    except ContractError as err:
        sys.stderr.write(f"Contract error [{err.code}]: {err.message}\n")
        return 2
    except Exception as err:
        sys.stderr.write(f"Error: {err}\n")
        return 2

    engine = MockEngine(contract)
    try:
        with serve(engine, host=args.host, port=args.port) as srv:
            sys.stdout.write(f"Serving contract mock on {srv.url}\n")
            sys.stdout.flush()
            while True:
                time.sleep(1.0)
    except KeyboardInterrupt:
        return 0
    except Exception as err:
        sys.stderr.write(f"Server error: {err}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
