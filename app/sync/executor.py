"""Uma rodada de sincronização: trava, registra e chama cada fonte."""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import func, select, text, update

from app.extensions import db
from app.models import SyncExecucao, SyncMarca
from app.sync import despesa, receita
from app.sync.cliente import ClienteApi

# Duas rodadas ao mesmo tempo (laço automático + botão) gravariam por cima.
CHAVE_TRAVA = 7_220_601


def _cliente(fonte: str) -> ClienteApi | None:
    cfg = current_app.config
    base, token = {
        "receita": (cfg.get("RECEITA_API_URL"), cfg.get("RECEITA_API_TOKEN")),
        "controle": (cfg.get("CONTROLE_API_URL"), cfg.get("CONTROLE_API_TOKEN")),
    }[fonte]
    if not base or not token:
        return None
    return ClienteApi(base, token, timeout=cfg.get("SYNC_TIMEOUT", 30))


def precisa_completa(session, agora: datetime | None = None) -> bool:
    """Uma recarga completa por dia, a partir da SYNC_HORA_COMPLETA."""
    agora = agora or datetime.now().astimezone()
    if agora.hour < current_app.config.get("SYNC_HORA_COMPLETA", 3):
        return False
    ultima = session.scalar(select(func.min(SyncMarca.ultima_completa_em)))
    return ultima is None or agora - ultima > timedelta(hours=20)


def sincronizar(
    fontes=("receita", "controle"),
    completo: bool | None = None,
    disparo: str = "automatico",
    usuario_id: int | None = None,
) -> SyncExecucao | None:
    """Devolve a execução registrada, ou None se outra rodada já está em andamento."""
    trava = db.engine.connect()
    travou = False
    try:
        travou = trava.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": CHAVE_TRAVA}).scalar()
        if not travou:
            return None

        session = db.session
        if completo is None:
            completo = precisa_completa(session)
        execucao = SyncExecucao(
            disparo="noturno" if completo and disparo == "automatico" else disparo,
            usuario_id=usuario_id,
        )
        session.add(execucao)
        session.commit()

        contagens, erros = {}, []
        for fonte in fontes:
            modulo = receita if fonte == "receita" else despesa
            try:
                cliente = _cliente(fonte)
                if cliente is None:
                    contagens[fonte] = "não configurada"
                    continue
                contagens[fonte] = modulo.sincronizar(session, cliente, completo=completo)
                session.commit()
            except Exception as erro:  # uma fonte fora do ar não derruba a outra
                session.rollback()
                current_app.logger.warning("sync %s falhou: %s", fonte, erro)
                erros.append(f"{fonte}: {erro}")

        if completo and not erros:
            session.execute(update(SyncMarca).values(ultima_completa_em=func.now()))
        execucao = session.get(SyncExecucao, execucao.id)
        execucao.contagens = contagens
        execucao.terminado_em = func.now()
        sucesso = [f for f in fontes if isinstance(contagens.get(f), dict)]
        execucao.status = "ok" if not erros else ("parcial" if sucesso else "erro")
        execucao.erro = "\n".join(erros)[:4000] or None
        session.commit()
        return execucao
    finally:
        if travou:
            trava.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": CHAVE_TRAVA})
            trava.commit()
        trava.close()


def ultima_ok(session) -> SyncExecucao | None:
    return session.scalars(
        select(SyncExecucao)
        .where(SyncExecucao.status.in_(("ok", "parcial")))
        .order_by(SyncExecucao.iniciado_em.desc())
        .limit(1)
    ).first()
