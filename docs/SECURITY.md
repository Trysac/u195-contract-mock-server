# Security notes

## Threat Model

This utility is a library that operates without network access (except for the optional `serve` server) and has no runtime dependencies (stdlib only).

### Defended
- **Untrusted input**: `load_contract` validates input against a schema and enforces strict size limits (`MAX_CONTRACT_BYTES`) and recursion depth (`MAX_CONTRACT_DEPTH`).
- **JSON Injection**: The standard library `json` module is used for parsing/serializing.

### Not Defended
- **Denial of Service**: The HTTP server accepts any valid connection. While individual requests are bounded by `max_body_bytes`, extreme request volume could exhaust local resources.