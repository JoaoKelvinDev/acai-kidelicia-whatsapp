from app.parsers.normalize import clean_lines, fold


def test_removes_emojis_asterisks_and_bullets_keeping_values():
    lines = clean_lines("🛵 *Modalidade:*   Delivery\n• *Cremes:* Creme de Ninho, Creme de Cupuaçu")
    assert lines == ["Modalidade: Delivery", "Cremes: Creme de Ninho, Creme de Cupuaçu"]


def test_crlf_and_lone_cr_are_line_breaks():
    assert clean_lines("Nome: Ana\r\nTelefone: 1\rBase: X") == [
        "Nome: Ana",
        "Telefone: 1",
        "Base: X",
    ]


def test_separator_and_blank_lines_are_dropped():
    assert clean_lines("A\n\n------------------------------\n   \nB") == ["A", "B"]


def test_replacement_char_inside_word_is_preserved_but_loose_one_removed():
    lines = clean_lines("� Cremes: Creme de Cupua�u ��")
    assert lines == ["Cremes: Creme de Cupua�u"]


def test_skin_tone_and_variation_selectors_removed():
    assert clean_lines("👍🏽 Obrigado ❤️") == ["Obrigado"]


def test_hyphen_inside_text_is_kept():
    assert clean_lines("Novo pedido - Açaí Ki-Delícia PL") == ["Novo pedido - Açaí Ki-Delícia PL"]


def test_fold_removes_accents_case_and_punctuation():
    assert fold("  Ponto de Referência: ") == "ponto de referencia"
    assert fold("Endere�o") == "endereo"
