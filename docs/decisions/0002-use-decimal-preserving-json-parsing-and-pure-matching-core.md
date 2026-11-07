# Use Decimal-preserving JSON parsing and pure matching core

Status: accepted (generated, pending human review)

## Context

Consumer contracts require verifying numeric equality (e.g. 3 == 3.0) while preserving string exactness for responses without floating-point precision loss. Full Pact tooling introduces external broker and runtime dependencies, which complicate unit testing environments.

## Decision

Implement contract parsing and body handling with parse_float=Decimal and parse_int=Decimal via standard library json. The MockEngine is purely functional and detached from socket I/O, allowing instantaneous in-process testing as well as execution inside an HTTP daemon thread via serve().

## Consequences

Zero external runtime dependencies. Numeric equality handles whole decimal comparisons reliably, and response decimals maintain their formatting text. MockEngine can be embedded directly in test suites without network overhead.
