"""Core contract loading, request matching engine, and HTTP server for contract-mock/1."""

from __future__ import annotations

import http.server
import json
import logging
import re
import threading
from collections import deque
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

ContractErrorCode = Literal["input_too_large", "invalid_contract", "unsupported_format", "too_deep"]

MAX_CONTRACT_DEPTH = 64
DEFAULT_MAX_CONTRACT_BYTES = 5_000_000
DEFAULT_MAX_BODY_BYTES = 1_048_576
DEFAULT_MAX_LOG = 1000


class ContractError(Exception):
    """Base error raised when loading or validating a contract file."""

    def __init__(self, code: ContractErrorCode, message: str) -> None:
        super().__init__(f"[{code}] {message[:200]}")
        self.code: ContractErrorCode = code
        self.message: str = message[:200]


class _DecimalEncoder(json.JSONEncoder):
    """JSON encoder that renders Decimal values as raw numbers."""

    def encode(self, o: Any) -> str:
        res = super().encode(o)
        return re.sub(r'"__DECIMAL__:([^"]+)"', r"\1", res)


def _encode_json(obj: Any) -> bytes:
    """Encode JSON preserving Decimal literal representation without quotes."""

    def _transform(node: Any) -> Any:
        if isinstance(node, Decimal):
            return f"__DECIMAL__:{node}"
        if isinstance(node, dict):
            return {k: _transform(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_transform(v) for v in node]
        return node

    transformed = _transform(obj)
    out = json.dumps(transformed, cls=_DecimalEncoder, separators=(",", ":"))
    return out.encode("utf-8")


def _parse_json(data: str | bytes) -> Any:
    """Parse JSON with parse_float and parse_int set to Decimal."""
    return json.loads(data, parse_float=Decimal, parse_int=Decimal)


@dataclass(frozen=True)
class Request:
    """Immutable HTTP request representation."""

    method: str
    path: str
    query: Mapping[str, list[str]]
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class Response:
    """Immutable HTTP response representation."""

    status: int
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class LogEntry:
    """Log entry for handled requests."""

    method: str
    path: str
    matched: str | None


@dataclass(frozen=True)
class ExpectedRequest:
    method: str
    path_pattern: str
    path_segments: tuple[str, ...]
    query: dict[str, list[str]]
    headers: dict[str, str]  # lowercase keys
    has_body: bool
    body: Any


@dataclass(frozen=True)
class ExpectedResponse:
    status: int
    headers: dict[str, str]
    has_body: bool
    body: Any


@dataclass(frozen=True)
class Interaction:
    """A single request/response interaction specification."""

    description: str
    request: ExpectedRequest
    response: ExpectedResponse


@dataclass(frozen=True)
class Contract:
    """Validated contract-mock/1 contract."""

    format: str
    interactions: tuple[Interaction, ...]


def _split_path(path: str) -> tuple[str, ...]:
    clean = path.strip("/")
    if not clean:
        return ()
    return tuple(clean.split("/"))


def _match_path(pattern_segments: tuple[str, ...], actual_segments: tuple[str, ...]) -> bool:
    if len(pattern_segments) != len(actual_segments):
        return False
    for p, a in zip(pattern_segments, actual_segments, strict=True):
        if p.startswith("{") and p.endswith("}"):
            # Template matches exactly one non-empty segment
            if len(a) == 0:
                return False
        else:
            if p != a:
                return False
    return True


def _check_depth(node: Any, current_depth: int = 1, max_depth: int = MAX_CONTRACT_DEPTH) -> None:
    if current_depth > max_depth:
        raise ContractError("too_deep", f"Contract nesting depth exceeds limit of {max_depth}")
    if isinstance(node, dict):
        for v in node.values():
            _check_depth(v, current_depth + 1, max_depth)
    elif isinstance(node, list):
        for item in node:
            _check_depth(item, current_depth + 1, max_depth)


def load_contract(text: str, *, max_bytes: int = DEFAULT_MAX_CONTRACT_BYTES) -> Contract:
    """Load and validate a 'contract-mock/1' contract string."""
    encoded_len = len(text.encode("utf-8"))
    if encoded_len > max_bytes:
        raise ContractError(
            "input_too_large",
            f"Contract size {encoded_len} bytes exceeds maximum allowed {max_bytes} bytes",
        )

    try:
        raw = _parse_json(text)
    except RecursionError as e:
        raise ContractError("too_deep", "Contract nesting depth exceeded recursion limit") from e
    except Exception as e:
        raise ContractError("invalid_contract", f"Invalid JSON: {e}") from e

    _check_depth(raw)

    if not isinstance(raw, dict):
        raise ContractError("invalid_contract", "Root must be an object")

    fmt = raw.get("format")
    if fmt != "contract-mock/1":
        if fmt is None or not isinstance(fmt, str):
            raise ContractError("invalid_contract", "Missing or invalid 'format' attribute")
        raise ContractError("unsupported_format", f"Unsupported format: '{fmt}'")

    raw_interactions = raw.get("interactions")
    if not isinstance(raw_interactions, list):
        raise ContractError("invalid_contract", "Attribute 'interactions' must be a list")

    seen_descriptions: set[str] = set()
    interactions: list[Interaction] = []

    for idx, item in enumerate(raw_interactions):
        loc = f"interactions[{idx}]"
        if not isinstance(item, dict):
            raise ContractError("invalid_contract", f"{loc} must be an object")

        desc = item.get("description")
        if not isinstance(desc, str) or not desc.strip():
            raise ContractError("invalid_contract", f"{loc}.description must be a non-empty string")
        if desc in seen_descriptions:
            raise ContractError("invalid_contract", f"Duplicate interaction description: '{desc}'")
        seen_descriptions.add(desc)

        req_obj = item.get("request")
        if not isinstance(req_obj, dict):
            raise ContractError("invalid_contract", f"{loc}.request must be an object")

        method = req_obj.get("method")
        if not isinstance(method, str) or not method:
            raise ContractError(
                "invalid_contract", f"{loc}.request.method must be a non-empty string"
            )

        path = req_obj.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            raise ContractError(
                "invalid_contract", f"{loc}.request.path must start with '/' leading slash"
            )

        query_raw = req_obj.get("query", {})
        if not isinstance(query_raw, dict):
            raise ContractError("invalid_contract", f"{loc}.request.query must be an object")
        query: dict[str, list[str]] = {}
        for qk, qv in query_raw.items():
            if (
                not isinstance(qk, str)
                or not isinstance(qv, list)
                or not all(isinstance(v, str) for v in qv)
            ):
                raise ContractError(
                    "invalid_contract", f"{loc}.request.query values must be lists of strings"
                )
            query[qk] = list(qv)

        headers_raw = req_obj.get("headers", {})
        if not isinstance(headers_raw, dict):
            raise ContractError("invalid_contract", f"{loc}.request.headers must be an object")
        headers: dict[str, str] = {}
        for hk, hv in headers_raw.items():
            if not isinstance(hk, str) or not isinstance(hv, str):
                raise ContractError(
                    "invalid_contract", f"{loc}.request.headers must be string key-value pairs"
                )
            headers[hk.lower()] = hv

        has_body = "body" in req_obj
        expected_body = req_obj.get("body")

        expected_request = ExpectedRequest(
            method=method.upper(),
            path_pattern=path,
            path_segments=_split_path(path),
            query=query,
            headers=headers,
            has_body=has_body,
            body=expected_body,
        )

        resp_obj = item.get("response")
        if not isinstance(resp_obj, dict):
            raise ContractError("invalid_contract", f"{loc}.response must be an object")

        if "status" not in resp_obj:
            raise ContractError("invalid_contract", f"{loc}.response.status missing")
        status = resp_obj.get("status")
        # Status must be an integer between 100 and 599
        if isinstance(status, Decimal):
            if status % 1 != 0:
                raise ContractError(
                    "invalid_contract", f"{loc}.response.status must be an integer 100-599"
                )
            status = int(status)
        if not isinstance(status, int) or isinstance(status, bool) or not (100 <= status <= 599):
            raise ContractError(
                "invalid_contract", f"{loc}.response.status must be an integer 100-599"
            )

        resp_headers_raw = resp_obj.get("headers", {})
        if not isinstance(resp_headers_raw, dict):
            raise ContractError("invalid_contract", f"{loc}.response.headers must be an object")
        resp_headers: dict[str, str] = {}
        for rhk, rhv in resp_headers_raw.items():
            if not isinstance(rhk, str) or not isinstance(rhv, str):
                raise ContractError(
                    "invalid_contract", f"{loc}.response.headers must be string key-value pairs"
                )
            resp_headers[rhk] = rhv

        resp_has_body = "body" in resp_obj
        resp_body = resp_obj.get("body")

        expected_response = ExpectedResponse(
            status=status,
            headers=resp_headers,
            has_body=resp_has_body,
            body=resp_body,
        )

        interactions.append(
            Interaction(
                description=desc,
                request=expected_request,
                response=expected_response,
            )
        )

    return Contract(format=fmt, interactions=tuple(interactions))


def _match_type(expected_type: str, actual_val: Any) -> bool:
    if expected_type == "any":
        return True
    if expected_type == "string":
        return isinstance(actual_val, str)
    if expected_type == "boolean":
        return isinstance(actual_val, bool)
    if expected_type == "null":
        return actual_val is None
    if expected_type == "array":
        return isinstance(actual_val, list)
    if expected_type == "object":
        return isinstance(actual_val, dict)
    if expected_type == "number":
        # booleans are not numbers
        if isinstance(actual_val, bool):
            return False
        return isinstance(actual_val, (Decimal, int, float))
    if expected_type == "integer":
        if isinstance(actual_val, bool):
            return False
        if isinstance(actual_val, int):
            return True
        if isinstance(actual_val, Decimal):
            return actual_val % 1 == 0
        return False
    return False


def _diff_body(expected: Any, actual: Any, path: str = "") -> str | None:
    """Return mismatch reason or None if matches."""
    # Check $type matching
    if isinstance(expected, dict) and len(expected) == 1 and "$type" in expected:
        t = expected["$type"]
        valid_types = {"string", "number", "integer", "boolean", "null", "array", "object", "any"}
        if t in valid_types:
            if not _match_type(cast(str, t), actual):
                loc = f"body{path}" if path else "body"
                return f"{loc}: expected type '{t}', got {type(actual).__name__}"
            return None

    # Dict matching: subset matching (expected keys must exist and match recursively)
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            loc = f"body{path}" if path else "body"
            return f"{loc}: expected object, got {type(actual).__name__}"
        for key, exp_val in expected.items():
            subpath = f"{path}.{key}" if path else f" {key}"
            if key not in actual:
                return f"body{subpath}: key missing"
            err = _diff_body(exp_val, actual[key], subpath)
            if err is not None:
                return err
        return None

    # Array matching: exact length and order
    if isinstance(expected, list):
        if not isinstance(actual, list):
            loc = f"body{path}" if path else "body"
            return f"{loc}: expected array, got {type(actual).__name__}"
        if len(expected) != len(actual):
            loc = f"body{path}" if path else "body"
            return f"{loc}: expected array of length {len(expected)}, got length {len(actual)}"
        for idx, (exp_item, act_item) in enumerate(zip(expected, actual, strict=True)):
            subpath = f"{path}[{idx}]"
            err = _diff_body(exp_item, act_item, subpath)
            if err is not None:
                return err
        return None

    # Numbers: Decimal handles 3 == 3.0
    if isinstance(expected, (Decimal, int, float)) and isinstance(actual, (Decimal, int, float)):
        if isinstance(expected, bool) or isinstance(actual, bool):
            if expected is not actual:
                loc = f"body{path}" if path else "body"
                return f"{loc}: expected {expected!r}, got {actual!r}"
            return None
        if Decimal(str(expected)) != Decimal(str(actual)):
            loc = f"body{path}" if path else "body"
            return f"{loc}: expected {expected}, got {actual}"
        return None

    # Scalar exact match
    if expected != actual:
        loc = f"body{path}" if path else "body"
        return f"{loc}: expected {expected!r}, got {actual!r}"

    return None


class MockEngine:
    """Core matching engine and request processor."""

    def __init__(
        self,
        contract: Contract,
        *,
        max_log: int = DEFAULT_MAX_LOG,
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        self._contract = contract
        self._max_body_bytes = max_body_bytes
        self._matched_interactions: set[str] = set()
        self.log: deque[LogEntry] = deque(maxlen=max_log)

    def unused(self) -> list[str]:
        """Return the descriptions of interactions never matched, in file order."""
        return [
            i.description
            for i in self._contract.interactions
            if i.description not in self._matched_interactions
        ]

    def handle(self, req: Request) -> Response:
        """Handle an incoming Request and return a Response."""
        # Check request body size limit first before parsing
        if len(req.body) > self._max_body_bytes:
            return Response(
                status=413,
                headers={"Content-Type": "application/json"},
                body=b'{"error":"body_too_large"}',
            )

        req_method = req.method.upper()
        req_segments = _split_path(req.path)

        # Standardize headers to lowercase for lookup
        req_headers_lower = {k.lower(): v for k, v in req.headers.items()}

        parsed_req_body: Any = None
        req_body_parsed = False
        req_body_invalid_json = False

        candidate_mismatches: list[dict[str, str]] = []

        for interaction in self._contract.interactions:
            exp_req = interaction.request

            # Match method (case-insensitive in request comparison)
            if exp_req.method != req_method:
                continue

            # Match path
            if not _match_path(exp_req.path_segments, req_segments):
                continue

            # Method and path matched: check query, headers, body
            mismatch_reason: str | None = None

            # Check query subset
            for q_name, q_expected_vals in exp_req.query.items():
                if q_name not in req.query:
                    mismatch_reason = f"query {q_name}: expected {q_expected_vals}, got missing"
                    break
                actual_vals = req.query[q_name]
                if actual_vals != q_expected_vals:
                    mismatch_reason = (
                        f"query {q_name}: expected {q_expected_vals}, got {actual_vals}"
                    )
                    break

            # Check headers
            if mismatch_reason is None:
                for h_name, h_expected_val in exp_req.headers.items():
                    if (
                        h_name not in req_headers_lower
                        or req_headers_lower[h_name] != h_expected_val
                    ):
                        # Actual header values are never echoed for security
                        mismatch_reason = f"header {h_name}: expected {h_expected_val}"
                        break

            # Check body if specified
            if mismatch_reason is None and exp_req.has_body:
                if not req_body_parsed:
                    req_body_parsed = True
                    if not req.body:
                        req_body_invalid_json = True
                    else:
                        try:
                            parsed_req_body = _parse_json(req.body)
                        except Exception:
                            req_body_invalid_json = True

                if req_body_invalid_json:
                    mismatch_reason = "body: not valid JSON"
                else:
                    diff = _diff_body(exp_req.body, parsed_req_body)
                    if diff is not None:
                        mismatch_reason = diff

            if mismatch_reason is None:
                # Interaction matched!
                self._matched_interactions.add(interaction.description)
                self.log.append(
                    LogEntry(method=req.method, path=req.path, matched=interaction.description)
                )
                return self._render_response(interaction.response)

            candidate_mismatches.append(
                {
                    "interaction": interaction.description,
                    "reason": mismatch_reason,
                }
            )

        # No match found
        self.log.append(LogEntry(method=req.method, path=req.path, matched=None))
        # Limit mismatches to at most 3
        mismatches_report = candidate_mismatches[:3]
        resp_payload = {
            "error": "no_matching_interaction",
            "mismatches": mismatches_report,
        }
        return Response(
            status=404,
            headers={"Content-Type": "application/json"},
            body=_encode_json(resp_payload),
        )

    def _render_response(self, resp: ExpectedResponse) -> Response:
        headers = dict(resp.headers)
        if resp.status == 204:
            return Response(status=204, headers=headers, body=b"")

        # Set Content-Type: application/json unless contract sets one
        has_ct = any(k.lower() == "content-type" for k in headers)
        if not has_ct and resp.has_body:
            headers["Content-Type"] = "application/json"

        body_bytes = _encode_json(resp.body) if resp.has_body else b""

        return Response(status=resp.status, headers=headers, body=body_bytes)


@dataclass(frozen=True)
class Server:
    """Running HTTP mock server details."""

    url: str


class _MockHttpHandler(http.server.BaseHTTPRequestHandler):
    server: _MockThreadingServer

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress default http.server stderr logging
        pass

    def do_GET(self) -> None:
        self._handle_any()

    def do_POST(self) -> None:
        self._handle_any()

    def do_PUT(self) -> None:
        self._handle_any()

    def do_DELETE(self) -> None:
        self._handle_any()

    def do_PATCH(self) -> None:
        self._handle_any()

    def do_HEAD(self) -> None:
        self._handle_any()

    def do_OPTIONS(self) -> None:
        self._handle_any()

    def _handle_any(self) -> None:
        # Read body
        content_len_header = self.headers.get("Content-Length")
        body = b""
        if content_len_header is not None:
            try:
                length = int(content_len_header)
                body = self.rfile.read(length)
            except ValueError:
                body = b""

        parsed_url = urlparse(self.path)
        raw_query = parse_qs(parsed_url.query, keep_blank_values=True)

        req_headers = {k: v for k, v in self.headers.items()}

        req = Request(
            method=self.command,
            path=parsed_url.path,
            query=raw_query,
            headers=req_headers,
            body=body,
        )

        engine = self.server.engine
        resp = engine.handle(req)

        self.send_response(resp.status)
        for hk, hv in resp.headers.items():
            self.send_header(hk, hv)
        if resp.body:
            self.send_header("Content-Length", str(len(resp.body)))
        self.end_headers()
        if resp.body:
            self.wfile.write(resp.body)


class _MockThreadingServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], engine: MockEngine) -> None:
        self.engine = engine
        super().__init__(server_address, _MockHttpHandler)


@contextmanager
def serve(engine: MockEngine, *, host: str = "127.0.0.1", port: int = 0) -> Iterator[Server]:
    """Run MockEngine backed by a ThreadingHTTPServer in a background daemon thread."""
    httpd = _MockThreadingServer((host, port), engine)
    actual_port = httpd.server_port
    url = f"http://{host}:{actual_port}"
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    try:
        yield Server(url=url)
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_thread.join(timeout=2.0)
