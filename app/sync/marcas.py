"""Marcas d'água por fonte e recurso."""

from __future__ import annotations

from app.models import SyncMarca


def marca(session, fonte: str, recurso: str) -> SyncMarca:
    registro = session.get(SyncMarca, (fonte, recurso))
    if registro is None:
        registro = SyncMarca(fonte=fonte, recurso=recurso)
        session.add(registro)
        session.flush()
    return registro


def salvar_marca(session) -> None:
    session.flush()
