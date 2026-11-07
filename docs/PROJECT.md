# Project record

## Objective
Mock HTTP server from consumer contract files: request matching (path templates, query, headers, JSON subset bodies), mismatch reports, and unused checks.

## Scope
- Public API: `load_contract`, `MockEngine`, `serve`.
- Local HTTP server implementation via `ThreadingHTTPServer`.
- Validation logic for `contract-mock/1` JSON schema.

## Out of scope
- OpenAPI documents.
- Pact broker integration or provider verification.
- Stateful scenarios.
- TLS/SSL.
- Regex-based matchers.

## Effort metrics

| Metric | Value |
|---|---|
| Tokens (input / output) | 1478653 / 23359 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.3351 |

## Factory run u195 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | gemini-3.8-flash | yes | 4427 | 15024 | 0 | 0 | 0.0298 |
| fix-1 | gemini-3.8-flash | no | 28512 | 997 | 0 | 73060 | 0.0306 |
| fix-2 | gemini-3.8-flash | no | 49147 | 2882 | 0 | 254646 | 0.0668 |
| fix-3 | gemini-3.8-flash | no | 63116 | 1285 | 0 | 309175 | 0.0753 |
| fix-4 | gemini-3.8-flash | no | 67278 | 1479 | 0 | 355736 | 0.0827 |
| audit | gemini-3.1-flash-lite | no | 47714 | 332 | 0 | 93437 | 0.0148 |
| docs | gemini-3.1-flash-lite | no | 132405 | 1360 | 0 | 0 | 0.0351 |

Total: $0.3351. Prices: Anthropic list prices.
