"""Painel administrativo: backups, restauracao, sincronizacao e perfis. Só admin."""

from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy import select

from app.admin import manutencao
from app.auditoria.servico import registrar
from app.auth.guardas import requer, usuario_atual
from app.extensions import db, limiter
from app.models import PERFIS, SyncExecucao, Usuario
from app.sync.executor import sincronizar as rodar_sync
from app.sync.pares import crs_sem_par

bp = Blueprint("admin", __name__, url_prefix="/administracao")


@bp.get("/")
@requer("admin")
def painel():
    return render_template(
        "admin/painel.html",
        secao="admin",
        backups=manutencao.listar_backups(),
        execucoes=db.session.scalars(
            select(SyncExecucao).order_by(SyncExecucao.iniciado_em.desc()).limit(30)
        ).all(),
        sem_par=crs_sem_par(db.session),
        pessoas=db.session.scalars(select(Usuario).order_by(Usuario.nome)).all(),
        perfis=PERFIS,
    )


@bp.post("/backups")
@requer("admin")
@limiter.limit("6 per minute")
def criar_backup():
    try:
        arquivo = manutencao.gerar_backup()
    except manutencao.ErroDeManutencao as erro:
        flash(str(erro), "erro")
        return redirect(url_for("admin.painel"))

    registrar(
        db.session,
        acao="manutencao.backup",
        usuario=usuario_atual(),
        alvo_tipo="backup",
        payload={"arquivo": arquivo.name, "bytes": arquivo.stat().st_size},
    )
    db.session.commit()
    flash(f"Backup gerado: {arquivo.name}", "")
    return redirect(url_for("admin.painel"))


@bp.get("/backups/<nome>")
@requer("admin")
def baixar_backup(nome: str):
    try:
        arquivo = manutencao.resolver_arquivo(nome)
    except manutencao.ErroDeManutencao as erro:
        flash(str(erro), "erro")
        return redirect(url_for("admin.painel"))
    return send_file(arquivo, as_attachment=True, download_name=arquivo.name)


@bp.post("/restauracao")
@requer("admin")
@limiter.limit("3 per minute")
def restauracao():
    if request.form.get("confirmacao") != manutencao.PALAVRA_RESTAURAR:
        flash(f'Digite "{manutencao.PALAVRA_RESTAURAR}" para confirmar a restauração.', "erro")
        return redirect(url_for("admin.painel"))

    nome = request.form.get("arquivo", "")
    usuario = usuario_atual()
    try:
        restaurado = manutencao.restaurar(db.session, nome)
    except manutencao.ErroDeManutencao as erro:
        flash(str(erro), "erro")
        return redirect(url_for("admin.painel"))

    # O registro vai depois, na conexao nova: o banco de agora e o do backup.
    registrar(
        db.session,
        acao="manutencao.restauracao",
        usuario=usuario,
        alvo_tipo="backup",
        payload={"arquivo": restaurado},
    )
    db.session.commit()
    flash(f"Banco restaurado a partir de {restaurado}.", "")
    return redirect(url_for("admin.painel"))


@bp.post("/pessoas/<int:identificador>/perfil")
@requer("admin")
def mudar_perfil(identificador: int):
    perfil = request.form.get("perfil", "")
    if perfil not in PERFIS:
        flash("Perfil desconhecido.", "erro")
        return redirect(url_for("admin.painel"))

    pessoa = db.session.get(Usuario, identificador)
    if pessoa is None:
        flash("Usuário não encontrado.", "erro")
        return redirect(url_for("admin.painel"))

    if pessoa.id == usuario_atual().id and perfil != "admin":
        flash("Você não pode rebaixar a si mesmo.", "erro")
        return redirect(url_for("admin.painel"))

    anterior, pessoa.perfil = pessoa.perfil, perfil
    registrar(
        db.session,
        acao="usuario.perfil",
        usuario=usuario_atual(),
        alvo_tipo="usuario",
        alvo_id=pessoa.id,
        payload={"email": pessoa.email, "de": anterior, "para": perfil},
    )
    db.session.commit()
    flash(f"{pessoa.nome} agora é {perfil}.", "")
    return redirect(url_for("admin.painel"))


@bp.post("/sincronizar")
@requer("admin")
@limiter.limit("6 per minute")
def sincronizar():
    usuario = usuario_atual()
    execucao = rodar_sync(disparo="manual", usuario_id=usuario.id)
    if execucao is None:
        flash("Já há uma sincronização em andamento. Tente de novo em instantes.", "erro")
    else:
        registrar(
            db.session,
            acao="sync.manual",
            usuario=usuario,
            alvo_tipo="sync",
            alvo_id=execucao.id,
            payload={"status": execucao.status},
        )
        db.session.commit()
        if execucao.status == "ok":
            flash("Sincronização concluída.", "")
        else:
            flash(
                f"Sincronização terminou com problema: {execucao.erro or execucao.status}", "erro"
            )
    return redirect(request.referrer or url_for("admin.painel"))
