"""Comandos de linha: promover usuario, listar usuarios e sincronizar.

O perfil nunca e concedido pela interface — e a mesma escolha do radar, e a
razao e que a tela de administracao existe para operar o sistema, nao para
distribuir poder sobre ele.
"""

from __future__ import annotations

import time

import click
from flask import Blueprint
from sqlalchemy import func, select

from app.extensions import db
from app.models import PERFIS, Usuario

bp = Blueprint("cli", __name__, cli_group=None)


@bp.cli.command("promover")
@click.argument("email")
@click.argument("perfil", type=click.Choice(PERFIS))
def promover(email: str, perfil: str) -> None:
    """Muda o perfil de alguem: flask promover fulano@x.com admin"""
    usuario = db.session.scalars(
        select(Usuario).where(func.lower(Usuario.email) == email.lower())
    ).first()
    if usuario is None:
        raise click.ClickException(
            f"{email} nao existe. A pessoa precisa entrar uma vez para ser criada."
        )

    anterior, usuario.perfil = usuario.perfil, perfil
    db.session.commit()
    click.echo(f"{usuario.nome}: {anterior} -> {perfil}")


@bp.cli.command("usuarios")
def usuarios() -> None:
    """Lista quem ja entrou no sistema."""
    pessoas = db.session.scalars(select(Usuario).order_by(Usuario.nome)).all()
    if not pessoas:
        click.echo("ninguem entrou ainda")
        return
    for pessoa in pessoas:
        marca = "" if pessoa.ativo else "  (sem o grupo)"
        click.echo(f"{pessoa.perfil:9} {pessoa.email:40} {pessoa.nome}{marca}")


@bp.cli.command("sincronizar")
@click.option("--fonte", type=click.Choice(["receita", "controle"]), help="só uma das origens")
@click.option("--completo", is_flag=True, help="recarga completa (apaga o que sumiu da origem)")
def sincronizar(fonte: str | None, completo: bool) -> None:
    """Copia receita e despesa das origens. O serviço `sync` do compose roda isto em laço."""
    from app.sync.executor import sincronizar as rodar

    inicio = time.monotonic()
    execucao = rodar(
        fontes=(fonte,) if fonte else ("receita", "controle"), completo=completo or None
    )
    if execucao is None:
        click.echo("outra sincronização está em andamento; nada feito")
        return
    click.echo(f"{execucao.status} em {time.monotonic() - inicio:.0f}s ({execucao.disparo})")
    for origem, contagens in (execucao.contagens or {}).items():
        click.echo(f"  {origem}: {contagens}")
    if execucao.erro:
        raise click.ClickException(execucao.erro)
