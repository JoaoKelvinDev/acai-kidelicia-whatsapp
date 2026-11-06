from decimal import Decimal

import pytest

from app.domain.enums import Modality, PaymentMethod
from app.parsers.site_order import is_site_order, parse_site_order
from tests.conftest import START, load_order


def parse(text: str):
    return parse_site_order(text, conversation_id="c1", source_message_id="m1", now=START)


def test_reference_message_is_extracted_field_by_field():
    draft = parse(load_order("referencia_invalida"))
    assert draft.name == "Teste"
    assert draft.phone_raw == "00000000000"
    assert draft.modality is Modality.DELIVERY
    assert draft.address == "Teste"
    assert draft.reference == "Teste"
    assert draft.delivery_fee == Decimal("3.00")
    assert draft.delivery_fee_verified is False
    assert draft.payment is PaymentMethod.PIX
    assert len(draft.items) == 1
    item = draft.items[0]
    assert item.quantity == 1
    assert item.size == "Copo 500ml"
    assert item.base == "Açaí Zero"
    assert item.creams == [
        "Creme de Maracujá",
        "Creme de Cupuaçu",
        "Creme de Nutela",
        "Creme de Ninho",
    ]
    assert item.ice_creams == [
        "Abacaxi",
        "Prestígio",
        "Babalu",
        "Terremoto",
        "Bombom Ferrero",
        "Tapioca",
    ]
    assert item.extras == ["Leite Condensado", "Côco Ralado", "Amendoim"]
    assert draft.unknown_fields == []
    assert draft.unparsed_lines == []


@pytest.mark.parametrize("line_break", ["\n", "\r\n"])
def test_whatsapp_formatting_does_not_change_extraction(line_break):
    plain = parse(load_order("delivery_pix_valido"))
    decorated_text = load_order("formatado_whatsapp").replace("\n", line_break)
    decorated = parse(decorated_text)
    for attr in ("name", "phone_raw", "modality", "address", "reference", "payment"):
        assert getattr(decorated, attr) == getattr(plain, attr), attr
    assert decorated.delivery_fee == Decimal("3.00")  # "R$ 3,00" com vírgula
    assert decorated.items == plain.items
    assert decorated.unknown_fields == []
    assert decorated.unparsed_lines == []


def test_two_items_keep_separate_quantities_and_choices():
    draft = parse(load_order("dois_itens"))
    assert [i.quantity for i in draft.items] == [2, 1]
    assert [i.size for i in draft.items] == ["Copo 500ml", "Copo 300ml"]
    assert draft.items[0].creams == ["Creme de Ninho"]
    assert draft.items[1].creams == ["Creme de Maracujá", "Creme de Cupuaçu"]
    assert draft.items[1].ice_creams == []
    assert draft.items[1].extras == ["Granola", "Mel"]


def test_empty_lists_are_legitimate():
    draft = parse(load_order("sem_adicionais"))
    item = draft.items[0]
    assert item.creams == [] and item.ice_creams == [] and item.extras == []
    assert draft.unparsed_lines == []


def test_unknown_labels_and_loose_lines_are_kept_not_dropped():
    draft = parse(load_order("ambiguo"))
    assert draft.items[0].size is None
    assert [f.label for f in draft.items[0].unknown_fields] == ["Observação"]
    assert draft.unparsed_lines == ["e mais um de 300 igual"]


def test_item_without_quantity_label_starts_new_item_on_repeated_field():
    text = (
        "Novo pedido\nNome: Ana Paula\nPagamento: Pix\n"
        "Tamanho: Copo 300ml\nBase: Açaí\nTamanho: Copo 500ml\nBase: Açaí Zero"
    )
    draft = parse(text)
    assert [i.size for i in draft.items] == ["Copo 300ml", "Copo 500ml"]


def test_repeated_order_field_with_different_value_is_flagged():
    text = load_order("delivery_pix_valido") + "\nNome: Outra Pessoa\n"
    draft = parse(text)
    assert draft.name == "Mariana Souza"
    assert draft.repeated_fields == ["nome"]


def test_replacement_char_inside_label_and_value():
    text = (
        "Novo pedido\nNome: Ana Paula\nEndere�o: Rua S�o Jo�o, 10\nModalidade: Delivery\n"
        "Cremes: Creme de Cupua�u\nPagamento: Pix"
    )
    draft = parse(text)
    assert draft.address == "Rua S�o Jo�o, 10"
    assert draft.items[0].creams == ["Creme de Cupua�u"]


def test_payment_with_change_inline():
    text = load_order("delivery_dinheiro_sem_troco").replace(
        "Pagamento: Dinheiro", "Pagamento: Dinheiro (troco para R$ 50)"
    )
    draft = parse(text)
    assert draft.payment is PaymentMethod.CASH
    assert draft.change_needed is True
    assert draft.change_for == Decimal("50.00")


@pytest.mark.parametrize(
    "name",
    [
        "referencia_invalida",
        "delivery_pix_valido",
        "retirada_cartao_valido",
        "delivery_dinheiro_sem_troco",
        "dois_itens",
        "sem_adicionais",
        "ambiguo",
        "formatado_whatsapp",
    ],
)
def test_structured_orders_are_recognized(name):
    assert is_site_order(load_order(name))


@pytest.mark.parametrize(
    "text",
    [
        load_order("texto_livre"),
        "Oi",
        "Novo pedido",
        "Nome: Maria\nEndereço: Rua A, 10",
        "Quero um açaí de 500 com cremes de ninho",
        "",
    ],
)
def test_non_orders_are_not_recognized(text):
    assert not is_site_order(text)
