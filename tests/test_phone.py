import pytest

from app.domain.phone import check_br_phone, same_phone


@pytest.mark.parametrize(
    "raw",
    ["(11) 97412-3058", "11974123058", "+55 11 97412-3058", "5511974123058", "011974123058"],
)
def test_valid_mobile_normalizes_to_e164(raw):
    check = check_br_phone(raw)
    assert check.error is None
    assert check.normalized == "+5511974123058"


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ("00000000000", "ficticio"),
        ("11999999999", "ficticio"),
        ("11912345678", "ficticio"),
        ("11987654321", "ficticio"),
        ("10974123058", "ddd"),
        ("1197412", "formato"),
        ("11874123058", "formato"),
        ("", "vazio"),
        ("telefone", "vazio"),
    ],
)
def test_invalid_phones(raw, error):
    assert check_br_phone(raw).error == error


def test_landline_configurable():
    assert check_br_phone("(11) 3456-7012").normalized == "+551134567012"
    assert check_br_phone("(11) 3456-7012", accept_landline=False).error == "fixo_nao_aceito"


def test_same_phone_tolerates_missing_ninth_digit_in_wa_id():
    assert same_phone("+5511974123058", "5511974123058")
    assert same_phone("+5511974123058", "551174123058")
    assert not same_phone("+5511974123058", "5511963217045")
