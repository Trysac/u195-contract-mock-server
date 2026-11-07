# Testing

The repository includes `tests/test_contract_mock_server.py`, which covers:
- Loading and validating various contract inputs.
- Request matching logic (paths, templates, query strings, headers).
- Body matching logic (types, subsets, arrays).
- Error handling (ContractError codes).
- Server lifecycle (start, handle, shutdown).