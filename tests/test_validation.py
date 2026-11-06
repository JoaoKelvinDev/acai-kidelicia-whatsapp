from app.domain.enums import IssueKind
from app.domain.validation import validate_draft
from app.parsers.site_order import parse_site_order
from tests.conftest import OTHER_SENDER, SENDER, START, load_order, make_store


def check(text: str, sender: str = SENDER, **store_overrides):
    draft = parse_site_order(text, conversation_id=sender, source_message_id="m1", now=START)
    return validate_draft(draft, make_store(**store_overrides), sender)


def codes(result):
    return {(i.field, i.kind, i.code) for i in result.issues}


def test_reference_example_asks_for_corrections_not_review():
    result = check(load_order("referencia_invalida"))
    assert not result.requires_human
    assert result.pending_fields == ["nome", "telefone", "endereco", "referencia"]
    assert ("telefone", IssueKind.INVALID, "ficticio") in codes(result)
    assert ("nome", IssueKind.INVALID, "placeholder") in codes(result)


def test_valid_delivery_has_only_unverifiable_fee_note():
    result = check(load_order("delivery_pix_valido"))
    assert result.pending_fields == []
    assert not result.requires_human
    assert [(i.field, i.code) for i in result.notes] == [("taxa_entrega", "nao_verificada")]


def test_pickup_does_not_require_address_or_reference():
    result = check(load_order("retirada_cartao_valido"))
    assert result.issues == []


def test_cash_delivery_without_change_asks_for_change():
    result = check(load_order("delivery_dinheiro_sem_troco"))
    assert result.pending_fields == ["troco"]


def test_cash_delivery_with_change_yes_but_no_value_asks_value():
    text = load_order("delivery_dinheiro_sem_troco") + "\nTroco: sim\n"
    assert check(text).pending_fields == ["troco_valor"]


def test_cash_delivery_with_no_change_is_complete():
    text = load_order("delivery_dinheiro_sem_troco") + "\nTroco: não preciso\n"
    assert check(text).pending_fields == []


def test_pix_never_asks_for_change():
    result = check(load_order("delivery_pix_valido"))
    assert not any(i.field.startswith("troco") for i in result.issues)


def test_cash_pickup_does_not_ask_for_change():
    text = load_order("retirada_cartao_valido").replace("Pagamento: Cartão", "Pagamento: Dinheiro")
    assert check(text).pending_fields == []


def test_phone_differing_from_sender_is_a_note_not_rejection():
    result = check(load_order("delivery_pix_valido"), sender=OTHER_SENDER)
    assert result.pending_fields == []
    assert result.has_note("diferente_do_remetente")


def test_item_problems_require_human():
    result = check(load_order("ambiguo"))
    assert result.requires_human
    review = {(i.field, i.code) for i in result.review_issues}
    assert ("itens[1].tamanho", "ausente") in review
    assert ("itens[1]", "campos_desconhecidos") in review
    assert ("pedido", "linhas_nao_reconhecidas") in review


def test_size_checked_against_catalog_only_when_configured():
    text = load_order("delivery_pix_valido")
    assert not check(text).requires_human
    result = check(text, allowed_sizes=["Copo 300ml", "Copo 700ml"])
    assert ("itens[1].tamanho", "fora_do_catalogo") in {
        (i.field, i.code) for i in result.review_issues
    }
    assert not check(text, allowed_sizes=["copo 500ML"]).requires_human


def test_declared_no_reference_is_note():
    text = load_order("delivery_pix_valido").replace("Ao lado da padaria azul", "Não tem")
    result = check(text)
    assert result.pending_fields == []
    assert result.has_note("sem_referencia_declarada")


def test_reference_requirement_is_configurable():
    text = load_order("delivery_pix_valido").replace(
        "Ponto de referência: Ao lado da padaria azul\n", ""
    )
    assert check(text).pending_fields == ["referencia"]
    assert check(text, require_reference_for_delivery=False).pending_fields == []


def test_address_without_number_is_accepted():
    result = check(load_order("delivery_dinheiro_sem_troco"))
    assert "endereco" not in result.pending_fields


def test_unparseable_fee_goes_to_review():
    text = load_order("delivery_pix_valido").replace("R$ 3.00", "três reais")
    result = check(text)
    assert ("taxa_entrega", "nao_reconhecida") in {(i.field, i.code) for i in result.review_issues}


def test_zero_quantity_requires_human():
    text = load_order("delivery_pix_valido").replace("Quantidade: 1x", "Quantidade: 0x")
    result = check(text)
    assert ("itens[1].quantidade", "nao_inteira_positiva") in {
        (i.field, i.code) for i in result.review_issues
    }
