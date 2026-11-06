from decimal import Decimal

import pytest

from app.domain.enums import Modality, PaymentMethod
from app.parsers.money import find_amount, parse_brl
from app.parsers.values import (
    parse_change,
    parse_list,
    parse_modality,
    parse_payment,
    parse_quantity,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("R$ 3.00", Decimal("3.00")),
        ("R$ 3,00", Decimal("3.00")),
        ("3", Decimal("3.00")),
        ("R$3,5", Decimal("3.50")),
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("1.000", Decimal("1000.00")),
        ("Grátis", Decimal("0.00")),
        ("-2,00", Decimal("-2.00")),
        ("50 reais", Decimal("50.00")),
    ],
)
def test_parse_brl(raw, expected):
    assert parse_brl(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "3,", "1.23.4", "R$ ,50", "12,345,6"])
def test_parse_brl_rejects(raw):
    assert parse_brl(raw) is None


def test_find_amount_single_or_ambiguous():
    assert find_amount("troco pra 50, obrigado") == Decimal("50.00")
    assert find_amount("R$ 100,00") == Decimal("100.00")
    assert find_amount("20 ou 50") is None
    assert find_amount("sem valor") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Delivery", Modality.DELIVERY),
        ("Entrega", Modality.DELIVERY),
        ("quero que entreguem", Modality.DELIVERY),
        ("Retirada", Modality.PICKUP),
        ("vou buscar na loja", Modality.PICKUP),
        ("Retirada (sem taxa de entrega)", None),
        ("qualquer", None),
    ],
)
def test_parse_modality(raw, expected):
    assert parse_modality(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Pix", PaymentMethod.PIX),
        ("Cartão", PaymentMethod.CARD),
        ("cartao de debito", PaymentMethod.CARD),
        ("Maquininha", PaymentMethod.CARD),
        ("Dinheiro", PaymentMethod.CASH),
        ("Dinheiro (troco para 50)", PaymentMethod.CASH),
        ("Pix ou cartão", None),
        ("boleto", None),
    ],
)
def test_parse_payment(raw, expected):
    assert parse_payment(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1x", 1), ("2 x", 2), ("x3", 3), ("10", 10), ("0x", 0), ("1,5", None), ("dois", None)],
)
def test_parse_quantity(raw, expected):
    assert parse_quantity(raw) == expected


def test_parse_list_keeps_names_and_accepts_empty():
    assert parse_list("Leite Condensado, Côco Ralado, Amendoim") == [
        "Leite Condensado",
        "Côco Ralado",
        "Amendoim",
    ]
    assert parse_list("") == []
    assert parse_list("Nenhum") == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("não", (False, None)),
        ("Não preciso", (False, None)),
        ("sem troco", (False, None)),
        ("sim", (True, None)),
        ("sim, para 50", (True, Decimal("50.00"))),
        ("troco para R$ 100,00", (True, Decimal("100.00"))),
        ("50", (True, Decimal("50.00"))),
        ("não, vou pagar 50 certinho", (None, None)),
        ("talvez", (None, None)),
    ],
)
def test_parse_change(raw, expected):
    assert parse_change(raw) == expected
