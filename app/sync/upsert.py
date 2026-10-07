"""Gravação em lote por origem_id."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

LOTE = 1000


def upsert(session, modelo, linhas: list[dict]) -> int:
    if not linhas:
        return 0
    colunas = [c for c in linhas[0] if c != "origem_id"]
    for inicio in range(0, len(linhas), LOTE):
        lote = linhas[inicio : inicio + LOTE]
        comando = insert(modelo).values(lote)
        comando = comando.on_conflict_do_update(
            index_elements=["origem_id"], set_={c: comando.excluded[c] for c in colunas}
        )
        session.execute(comando)
    return len(linhas)


def apagar_ausentes(session, modelo, origem_ids: set[int]) -> int:
    """Recarga completa: o que não veio da origem deixou de existir lá."""
    locais = set(session.scalars(select(modelo.origem_id)).all())
    sobrando = locais - origem_ids
    for inicio in range(0, len(sobrando), LOTE):
        parte = list(sobrando)[inicio : inicio + LOTE]
        session.execute(delete(modelo).where(modelo.origem_id.in_(parte)))
    return len(sobrando)


def apagar(session, modelo, origem_ids: list[int]) -> int:
    if not origem_ids:
        return 0
    resultado = session.execute(delete(modelo).where(modelo.origem_id.in_(origem_ids)))
    return resultado.rowcount or 0
