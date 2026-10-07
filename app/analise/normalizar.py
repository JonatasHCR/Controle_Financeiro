"""Chaves de junção entre a Receita, o Controle de Despesa e a configuração."""

from __future__ import annotations

import re
import unicodedata

_ESPACOS = re.compile(r"\s+")


def cr_norm(codigo: str | None) -> str:
    """'04561 ' e '4561' são o mesmo CR."""
    limpo = _ESPACOS.sub("", str(codigo or "")).upper()
    return limpo.lstrip("0") or ("0" if limpo else "")


def nome_norm(nome: str | None) -> str:
    """Comparação de nomes sem acento, caixa ou espaço sobrando."""
    sem_acento = unicodedata.normalize("NFD", str(nome or ""))
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return _ESPACOS.sub(" ", sem_acento).strip().upper()
