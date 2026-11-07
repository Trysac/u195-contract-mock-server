"""Complete test suite for contract_mock_server exercising every feature and error branch."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from contract_mock_server import (
    ContractError,
    MockEngine,
    Request,
    load_contract,
    serve,
)
from contract_mock_server.__main__ import main


def test_acceptance_user_endpoint_decimal_preserved() -> None:
    contract_json = """{
        "format": "contract-mock/1",
        "interactions": [
            {
                "description": "get user",
                "request": {
                    "method": "GET",
                    "path": "/users/{id}"
                },
                "response": {
                    "status": 200,
                    "body": {"id": "42", "price": 1.10}
                }
            }
        ]
    }"""

    contract = load_contract(contract_json)
    engine = MockEngine(contract)
    res = engine.handle(Request("GET", "/users/42", {}, {}, b""))

    assert res.status == 200
    assert res.headers["Content-Type"] == "application/json"
    assert res.body == b'{"id":"42","price":1.10}'


def test_acceptance_path_templates_and_first_match_priority() -> None:
    contract_json = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": "first interaction",
                    "request": {"method": "GET", "path": "/users/{id}"},
                    "response": {"status": 200, "body": {"match": 1}},
                },
                {
                    "description": "second interaction",
                    "request": {"method": "GET", "path": "/users/{id}"},
                    "response": {"status": 200, "body": {"match": 2}},
                },
            ],
        }
    )
    contract = load_contract(contract_json)
    engine = MockEngine(contract)

    # '/users/42/x' and '/users/' do not match '/users/{id}'
    res_nested = engine.handle(Request("GET", "/users/42/x", {}, {}, b""))
    assert res_nested.status == 404
    assert json.loads(res_nested.body)["mismatches"] == []

    res_empty_seg = engine.handle(Request("GET", "/users/", {}, {}, b""))
    assert res_empty_seg.status == 404
    assert json.loads(res_empty_seg.body)["mismatches"] == []

    # method 'get' matches 'GET'
    res_case = engine.handle(Request("get", "/users/42", {}, {}, b""))
    assert res_case.status == 200
    assert json.loads(res_case.body) == {"match": 1}


def test_acceptance_query_matching_and_mismatch_report() -> None:
    contract_json = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": "get user",
                    "request": {
                        "method": "GET",
                        "path": "/users",
                        "query": {"page": ["2"]},
                    },
                    "response": {"status": 200, "body": {"ok": True}},
                }
            ],
        }
    )
    contract = load_contract(contract_json)
    engine = MockEngine(contract)

    # '?page=2&x=1' matches (subset)
    match_res = engine.handle(Request("GET", "/users", {"page": ["2"], "x": ["1"]}, {}, b""))
    assert match_res.status == 200

    # '?page=3' does not match, returns 404 with mismatches
    mismatch_res = engine.handle(Request("GET", "/users", {"page": ["3"]}, {}, b""))
    assert mismatch_res.status == 404
    assert json.loads(mismatch_res.body) == {
        "error": "no_matching_interaction",
        "mismatches": [
            {
                "interaction": "get user",
                "reason": "query page: expected ['2'], got ['3']",
            }
        ],
    }

    # missing query param
    missing_q = engine.handle(Request("GET", "/users", {}, {}, b""))
    assert missing_q.status == 404
    assert "expected ['2'], got missing" in json.loads(missing_q.body)["mismatches"][0]["reason"]


def test_acceptance_headers_case_insensitive_and_body_types() -> None:
    contract_json = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": "create item",
                    "request": {
                        "method": "POST",
                        "path": "/items",
                        "headers": {"Authorization": "Bearer secret"},
                        "body": {"name": {"$type": "string"}, "age": 3},
                    },
                    "response": {"status": 201, "body": {"created": True}},
                },
                {
                    "description": "array interaction",
                    "request": {
                        "method": "POST",
                        "path": "/array",
                        "body": [1, 2],
                    },
                    "response": {"status": 200},
                },
            ],
        }
    )
    contract = load_contract(contract_json)
    engine = MockEngine(contract)

    # Header names match case-insensitively ('authorization' matches 'Authorization')
    # expected body matches subset: name is string, age is 3 (3.0 equals 3), extra is allowed
    req_body = json.dumps({"name": "a", "age": 3.0, "extra": True}).encode("utf-8")
    res = engine.handle(Request("POST", "/items", {}, {"authorization": "Bearer secret"}, req_body))
    assert res.status == 201

    # Header mismatch (values never echoed)
    bad_hdr = engine.handle(
        Request("POST", "/items", {}, {"authorization": "Bearer wrong"}, req_body)
    )
    assert bad_hdr.status == 404
    assert (
        json.loads(bad_hdr.body)["mismatches"][0]["reason"]
        == "header authorization: expected Bearer secret"
    )

    # Array exact length and order
    res_arr_ok = engine.handle(Request("POST", "/array", {}, {}, b"[1,2]"))
    assert res_arr_ok.status == 200

    res_arr_order = engine.handle(Request("POST", "/array", {}, {}, b"[2,1]"))
    assert res_arr_order.status == 404
    assert "body[0]: expected 1, got 2" in json.loads(res_arr_order.body)["mismatches"][0]["reason"]

    res_arr_len = engine.handle(Request("POST", "/array", {}, {}, b"[1,2,3]"))
    assert res_arr_len.status == 404
    assert (
        "expected array of length 2, got length 3"
        in json.loads(res_arr_len.body)["mismatches"][0]["reason"]
    )


def test_acceptance_unused_and_bounded_log() -> None:
    contract_json = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": "first",
                    "request": {"method": "GET", "path": "/a"},
                    "response": {"status": 200},
                },
                {
                    "description": "second",
                    "request": {"method": "GET", "path": "/b"},
                    "response": {"status": 200},
                },
            ],
        }
    )
    contract = load_contract(contract_json)
    engine = MockEngine(contract, max_log=2)

    assert engine.unused() == ["first", "second"]

    engine.handle(Request("GET", "/a", {}, {}, b""))
    assert engine.unused() == ["second"]

    engine.handle(Request("GET", "/b", {}, {}, b""))
    assert engine.unused() == []

    # 3rd request
    engine.handle(Request("GET", "/c", {}, {}, b""))
    assert len(engine.log) == 2
    assert engine.log[0].path == "/b"
    assert engine.log[1].path == "/c"
    assert engine.log[1].matched is None


def test_acceptance_load_contract_error_codes() -> None:
    # unsupported_format
    with pytest.raises(ContractError) as exc_info:
        load_contract(json.dumps({"format": "other", "interactions": []}))
    assert exc_info.value.code == "unsupported_format"

    # missing response status naming interactions[0].response.status
    invalid_status_contract = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": "i1",
                    "request": {"method": "GET", "path": "/test"},
                    "response": {},
                }
            ],
        }
    )
    with pytest.raises(ContractError) as exc_info:
        load_contract(invalid_status_contract)
    assert exc_info.value.code == "invalid_contract"
    assert "interactions[0].response.status" in exc_info.value.message

    # input_too_large for 5_000_001 bytes
    large_input = " " * 5_000_001
    with pytest.raises(ContractError) as exc_info:
        load_contract(large_input)
    assert exc_info.value.code == "input_too_large"

    # nesting deeper than 64 raises too_deep
    deep_obj: dict[str, object] = {}
    curr = deep_obj
    for _ in range(70):
        child: dict[str, object] = {}
        curr["child"] = child
        curr = child
    deep_json = json.dumps({"format": "contract-mock/1", "interactions": [], "extra": deep_obj})
    with pytest.raises(ContractError) as exc_info:
        load_contract(deep_json)
    assert exc_info.value.code == "too_deep"


def test_acceptance_body_too_large_and_non_json_mismatch() -> None:
    contract_json = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": "post json",
                    "request": {
                        "method": "POST",
                        "path": "/data",
                        "body": {"valid": True},
                    },
                    "response": {"status": 200},
                }
            ],
        }
    )
    contract = load_contract(contract_json)
    engine = MockEngine(contract, max_body_bytes=100)

    # 101 bytes returns 413
    large_body = b"a" * 101
    res_413 = engine.handle(Request("POST", "/data", {}, {}, large_body))
    assert res_413.status == 413
    assert res_413.body == b'{"error":"body_too_large"}'

    # Non-JSON body against JSON expectation gives 'body: not valid JSON'
    res_bad_json = engine.handle(Request("POST", "/data", {}, {}, b"not a json"))
    assert res_bad_json.status == 404
    mismatches = json.loads(res_bad_json.body)["mismatches"]
    assert mismatches[0]["reason"] == "body: not valid JSON"


def test_acceptance_serve_and_cli(tmp_path: Path) -> None:
    contract_content = """{
        "format": "contract-mock/1",
        "interactions": [
            {
                "description": "get user",
                "request": {"method": "GET", "path": "/users/{id}"},
                "response": {"status": 200, "body": {"id": "42", "price": 1.10}}
            }
        ]
    }"""

    contract = load_contract(contract_content)
    engine = MockEngine(contract)

    with serve(engine) as srv:
        assert srv.url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(srv.url + "/users/42") as response:  # noqa: S310
            assert response.status == 200
            body = response.read()
            assert body == b'{"id":"42","price":1.10}'

    # Closed after block
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(srv.url + "/users/42")  # noqa: S310

    # CLI main(['--check', 'contract.json']) returns 0 for valid file and 2 otherwise
    valid_file = tmp_path / "valid.json"
    valid_file.write_text(contract_content, encoding="utf-8")
    assert main(["--check", str(valid_file)]) == 0

    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text('{"format": "bad"}', encoding="utf-8")
    assert main(["--check", str(invalid_file)]) == 2

    missing_file = tmp_path / "missing.json"
    assert main(["--check", str(missing_file)]) == 2


def test_type_matching_matrix() -> None:
    contract_json = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": "types check",
                    "request": {
                        "method": "POST",
                        "path": "/types",
                        "body": {
                            "s": {"$type": "string"},
                            "n": {"$type": "number"},
                            "i": {"$type": "integer"},
                            "b": {"$type": "boolean"},
                            "nil": {"$type": "null"},
                            "arr": {"$type": "array"},
                            "obj": {"$type": "object"},
                            "a": {"$type": "any"},
                        },
                    },
                    "response": {"status": 200},
                }
            ],
        }
    )
    contract = load_contract(contract_json)
    engine = MockEngine(contract)

    valid_body = {
        "s": "hello",
        "n": 4.2,
        "i": 10,
        "b": False,
        "nil": None,
        "arr": [1, 2],
        "obj": {"k": "v"},
        "a": ["anything"],
    }
    res = engine.handle(Request("POST", "/types", {}, {}, json.dumps(valid_body).encode("utf-8")))
    assert res.status == 200

    # Booleans are not numbers
    invalid_body = dict(valid_body)
    invalid_body["n"] = True
    res_fail = engine.handle(
        Request("POST", "/types", {}, {}, json.dumps(invalid_body).encode("utf-8"))
    )
    assert res_fail.status == 404
    assert "expected type 'number'" in json.loads(res_fail.body)["mismatches"][0]["reason"]

    # Float is not integer
    invalid_body2 = dict(valid_body)
    invalid_body2["i"] = 10.5
    res_fail2 = engine.handle(
        Request("POST", "/types", {}, {}, json.dumps(invalid_body2).encode("utf-8"))
    )
    assert res_fail2.status == 404
    assert "expected type 'integer'" in json.loads(res_fail2.body)["mismatches"][0]["reason"]

    # Integer can be boolean? No, booleans are not integers
    invalid_body3 = dict(valid_body)
    invalid_body3["i"] = True
    res_fail3 = engine.handle(
        Request("POST", "/types", {}, {}, json.dumps(invalid_body3).encode("utf-8"))
    )
    assert res_fail3.status == 404


def test_additional_validation_errors() -> None:
    # Malformed JSON
    with pytest.raises(ContractError) as exc:
        load_contract("{not valid json}")
    assert exc.value.code == "invalid_contract"

    # Root not object
    with pytest.raises(ContractError) as exc:
        load_contract("[]")
    assert exc.value.code == "invalid_contract"

    # Missing format
    with pytest.raises(ContractError) as exc:
        load_contract('{"interactions": []}')
    assert exc.value.code == "invalid_contract"

    # Interactions not list
    with pytest.raises(ContractError) as exc:
        load_contract('{"format": "contract-mock/1", "interactions": 123}')
    assert exc.value.code == "invalid_contract"

    # Duplicate description
    dup_json = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": "dup",
                    "request": {"method": "GET", "path": "/1"},
                    "response": {"status": 200},
                },
                {
                    "description": "dup",
                    "request": {"method": "GET", "path": "/2"},
                    "response": {"status": 200},
                },
            ],
        }
    )
    with pytest.raises(ContractError) as exc:
        load_contract(dup_json)
    assert exc.value.code == "invalid_contract"
    assert "Duplicate interaction" in exc.value.message

    # Invalid path without leading slash
    bad_path = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": "bad",
                    "request": {"method": "GET", "path": "users"},
                    "response": {"status": 200},
                },
            ],
        }
    )
    with pytest.raises(ContractError) as exc:
        load_contract(bad_path)
    assert exc.value.code == "invalid_contract"

    # Invalid response status
    bad_status = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": "bad",
                    "request": {"method": "GET", "path": "/u"},
                    "response": {"status": 999},
                },
            ],
        }
    )
    with pytest.raises(ContractError) as exc:
        load_contract(bad_status)
    assert exc.value.code == "invalid_contract"

    # Non-integer decimal status
    bad_dec_status = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": "bad",
                    "request": {"method": "GET", "path": "/u"},
                    "response": {"status": 200.5},
                },
            ],
        }
    )
    with pytest.raises(ContractError) as exc:
        load_contract(bad_dec_status)
    assert exc.value.code == "invalid_contract"


def test_status_204_and_custom_content_type() -> None:
    contract_json = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": "no content",
                    "request": {"method": "DELETE", "path": "/item"},
                    "response": {"status": 204, "body": {"ignore": "me"}},
                },
                {
                    "description": "custom content type",
                    "request": {"method": "GET", "path": "/custom"},
                    "response": {
                        "status": 200,
                        "headers": {"Content-Type": "text/plain"},
                        "body": "hello",
                    },
                },
            ],
        }
    )
    contract = load_contract(contract_json)
    engine = MockEngine(contract)

    res_204 = engine.handle(Request("DELETE", "/item", {}, {}, b""))
    assert res_204.status == 204
    assert res_204.body == b""

    res_custom = engine.handle(Request("GET", "/custom", {}, {}, b""))
    assert res_custom.status == 200
    assert res_custom.headers["Content-Type"] == "text/plain"
    assert res_custom.body == b'"hello"'


def test_mismatch_limits_and_details() -> None:
    contract_json = json.dumps(
        {
            "format": "contract-mock/1",
            "interactions": [
                {
                    "description": f"i{idx}",
                    "request": {"method": "GET", "path": "/test", "query": {"p": [str(idx)]}},
                    "response": {"status": 200},
                }
                for idx in range(5)
            ],
        }
    )
    contract = load_contract(contract_json)
    engine = MockEngine(contract)

    res = engine.handle(Request("GET", "/test", {"p": ["99"]}, {}, b""))
    assert res.status == 404
    mismatches = json.loads(res.body)["mismatches"]
    assert len(mismatches) == 3


def test_cli_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # CLI without args prints usage and returns 2
    assert main([]) == 2

    # CLI with non-existent file
    assert main(["non_existent.json"]) == 2

    # CLI with invalid contract file
    invalid_file = tmp_path / "invalid_run.json"
    invalid_file.write_text('{"format": "invalid"}', encoding="utf-8")
    assert main([str(invalid_file)]) == 2

    # CLI serve execution interrupted by KeyboardInterrupt
    valid_file = tmp_path / "valid_run.json"
    valid_file.write_text(
        json.dumps(
            {
                "format": "contract-mock/1",
                "interactions": [
                    {
                        "description": "cli run",
                        "request": {"method": "GET", "path": "/run"},
                        "response": {"status": 200},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("time.sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt))
    assert main([str(valid_file), "--port", "0"]) == 0
