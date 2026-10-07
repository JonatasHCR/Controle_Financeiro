"""CRs que existem só numa das origens (aviso na administração e na configuração)."""

from __future__ import annotations

from sqlalchemy import select

from app.models import CdCentro, RcContrato


def crs_sem_par(session) -> dict[str, list[str]]:
    receita = set(session.scalars(select(RcContrato.cr_norm)))
    controle = set(session.scalars(select(CdCentro.cr_norm)))
    return {
        "so_receita": sorted(receita - controle, key=lambda c: (len(c), c)),
        "so_controle": sorted(controle - receita, key=lambda c: (len(c), c)),
    }
