"""Montagem de respostas a partir de templates internos configuráveis.

Nenhum texto do cliente é interpolado em templates (só dígitos finais do telefone).
"""

from app.domain.enums import IssueKind
from app.domain.models import Issue, OrderDraft
from app.domain.phone import last_digits
from app.domain.store import StoreSettings
from app.domain.validation import ValidationResult


class _SafeFormat(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(template: str, store: StoreSettings, **extra: str) -> str:
    values = _SafeFormat(store_name=store.store_name, website_url=store.website_url or "")
    values.update(extra)
    return template.format_map(values)


def ask_data_text(store: StoreSettings, issues: list[Issue], *, retry: bool) -> str:
    texts = store.texts
    lines = [texts.ask_data_retry_intro if retry else texts.ask_data_intro]
    seen: list[str] = []
    for issue in issues:
        if issue.field in seen:
            continue
        seen.append(issue.field)
        question = texts.field_questions.get(issue.field, f"Informe: {issue.field}")
        if issue.kind is IssueKind.INVALID:
            question += texts.invalid_suffix
        lines.append(f"• {question}")
    if len(seen) > 1:
        lines.append(texts.ask_data_format_hint)
    lines.append(texts.ask_data_outro)
    return render("\n".join(lines), store)


def confirmation_text(store: StoreSettings, draft: OrderDraft, result: ValidationResult) -> str:
    text = render(store.texts.confirmation, store)
    if result.has_note("diferente_do_remetente") and draft.phone_raw:
        note = render(store.texts.phone_divergence_note, store, last4=last_digits(draft.phone_raw))
        text = f"{text}\n\n{note}"
    return text
