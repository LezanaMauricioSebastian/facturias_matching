"""Tests for ?excel_user=1 / client aliases."""

from facturia_matching.padron.excel_user import (
    is_excel_user_request,
    matched_excel_alias,
    resolve_excel_company_id,
)


def test_excel_user_flag_truthy():
    assert is_excel_user_request(excel_user="1")
    assert is_excel_user_request(excel_user="true")
    assert not is_excel_user_request(excel_user="0")
    assert not is_excel_user_request()


def test_pepe_alias_enables_excel_user():
    assert is_excel_user_request(query_params={"pepe": "1"})
    assert matched_excel_alias({"pepe": "1"}) == "pepe"
    assert resolve_excel_company_id(query_params={"pepe": "1"}) == 0


def test_excel_company_falls_back_to_process():
    assert resolve_excel_company_id(process_company_id=42) == 42
    assert resolve_excel_company_id(process_company_id="7") == 7
    assert resolve_excel_company_id() == 0


def test_payload_excel_user():
    assert is_excel_user_request(payload={"excel_user": "1"})
    assert is_excel_user_request(payload={"pepe": "yes"})
