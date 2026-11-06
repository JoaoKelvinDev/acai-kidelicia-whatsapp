"""Interpretação determinística de respostas a campos pendentes.

Na dúvida, não atualiza nada: a tentativa é contada e, no limite, vai para humano.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.parsers.normalize import clean_lines
from app.parsers.site_order import LineKind, scan_line
from app.parsers.values import parse_change, parse_modality, parse_payment

_CHANGE_FIELDS = frozenset({"troco", "troco_valor"})


@dataclass
class PendingReply:
    updates: dict[str, str] = field(default_factory=dict)  # campo do pedido → valor bruto
    touches_items: bool = False
    unknown_labels: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return self.touches_items or bool(self.unknown_labels)


def parse_pending_reply(text: str, pending: Sequence[str]) -> PendingReply:
    lines = clean_lines(text)
    if not lines:
        return PendingReply()

    scanned = [scan_line(line) for line in lines]
    has_known_label = any(s.kind in (LineKind.ORDER_FIELD, LineKind.ITEM_FIELD) for s in scanned)
    # Sem rótulo conhecido, um ":" (ex.: "Bloco: B") é tratado como texto livre.
    if has_known_label:
        labeled = [
            s
            for s in scanned
            if s.kind in (LineKind.ORDER_FIELD, LineKind.ITEM_FIELD, LineKind.UNKNOWN_FIELD)
        ]
        reply = PendingReply()
        for s in labeled:
            if s.kind is LineKind.ORDER_FIELD and s.field:
                reply.updates[s.field] = s.value
            elif s.kind is LineKind.ITEM_FIELD:
                reply.touches_items = True
            else:
                reply.unknown_labels.append(s.label)
        return reply

    joined = ", ".join(lines)
    fields = list(dict.fromkeys(pending))
    if not fields:
        return PendingReply()
    if set(fields) <= _CHANGE_FIELDS:
        return PendingReply(updates={"troco": joined})
    if len(fields) == 1:
        return PendingReply(updates={fields[0]: joined})

    # Vários campos pendentes e resposta sem rótulo: só aceita um casamento inequívoco.
    candidates: dict[str, str] = {}
    if "pagamento" in fields and parse_payment(joined):
        candidates["pagamento"] = joined
    if "modalidade" in fields and parse_modality(joined):
        candidates["modalidade"] = joined
    if _CHANGE_FIELDS & set(fields) and parse_change(joined)[0] is not None:
        candidates["troco"] = joined
    digits = re.sub(r"\D", "", joined)
    if "telefone" in fields and len(digits) >= 10 and len(digits) >= len(joined.strip()) * 0.6:
        candidates["telefone"] = joined
    if len(candidates) == 1:
        return PendingReply(updates=candidates)
    return PendingReply()
