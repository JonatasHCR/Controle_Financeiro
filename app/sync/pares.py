"""Contratos da Receita sem centro de custo no Controle (aviso na administração).

O contrário (centro só no Controle) não interessa: sem contrato na Receita, as
despesas dele nem são trazidas.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import CdCentro, RcContrato


def crs_sem_par(session) -> dict[str, list[str]]:
    receita = set(session.scalars(select(RcContrato.cr_norm)))
    controle = set(session.scalars(select(CdCentro.cr_norm)))
    return {"so_receita": sorted(receita - controle, key=lambda c: (len(c), c))}
