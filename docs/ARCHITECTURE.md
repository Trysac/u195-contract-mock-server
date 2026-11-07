# Architecture

`contract-mock-server` implements a consumer-driven contract testing mock server. It provides both an in-memory matching engine and an HTTP server daemon.

## Components

1. **Contract Parser (`load_contract`)**: Enforces payload size/depth limits and validates `contract-mock/1` schema.
2. **Matching Engine (`MockEngine`)**: Evaluates requests in declaration order, using subset equality for query/headers and recursive subset matching for JSON bodies.
3. **HTTP Server (`serve`)**: Context manager running `ThreadingHTTPServer`.
4. **CLI**: Validation and serving via `argparse`.