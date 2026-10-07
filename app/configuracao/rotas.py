"""Configuração: complementos que a sincronização não traz. Perfil operador.

Nenhuma rota aqui cria contrato, NF ou despesa — esses vêm só da Receita e do
Controle de Despesa.
"""

from __future__ import annotations

import hashlib
import tempfile
from decimal import Decimal
from pathlib import Path

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from sqlalchemy import select

from app.analise.normalizar import cr_norm
from app.auditoria.servico import registrar
from app.auth.guardas import requer, usuario_atual
from app.configuracao import gravar, planilha
from app.configuracao.servico import (
    ErroDeValidacao,
    alvo_contratual,
    contrato_por_cr,
    data_br,
    decimal_br,
    linhas_do_form,
    mes_br,
    naturezas_do_cr,
    nfs_do_cr,
    opcao,
    status_dos_crs,
)
from app.extensions import db, limiter
from app.models import CfgItem, CfgPendencia, CfgPleito, ConfigImportacao, Parametros
from app.models.complementos import PRIORIDADES, STATUS_PENDENCIA, STATUS_PLEITO, TIPOS_PLEITO

bp = Blueprint("configuracao", __name__, url_prefix="/configuracao")

ABAS = (
    ("prazos", "Prazos"),
    ("itens", "Itens"),
    ("depara", "De-para"),
    ("bms", "BMs"),
    ("pendencias", "Pendências"),
    ("pleitos", "Pleitos"),
    ("parametros", "Parâmetros"),
)
ABAS_SEM_RECEITA = ("depara",)
PASTA_IMPORT = Path(tempfile.gettempdir()) / "controle-financeiro-importacoes"


@bp.get("/")
@requer("operador")
def lista():
    status = status_dos_crs(db.session)
    cr = cr_norm(request.args.get("cr", "")) or (status[0]["contrato"].cr if status else "")
    contrato = next((s["contrato"] for s in status if s["contrato"].cr == cr), None)
    aba = request.args.get("aba", "prazos")
    if contrato and not contrato.receita and aba not in ABAS_SEM_RECEITA:
        aba = "depara"
    contexto = {
        "secao": "configuracao",
        "status": status,
        "contrato": contrato,
        "aba": aba,
        "abas": ABAS,
        "abas_sem_receita": ABAS_SEM_RECEITA,
        "prioridades": PRIORIDADES,
        "status_pendencia": STATUS_PENDENCIA,
        "tipos_pleito": TIPOS_PLEITO,
        "status_pleito": STATUS_PLEITO,
    }
    if contrato:
        contexto.update(_dados_da_aba(contrato, aba))
    return render_template("configuracao/lista.html", **contexto)


def _dados_da_aba(contrato, aba: str) -> dict:
    sessao, cr = db.session, contrato.cr
    if aba == "itens":
        itens = sessao.scalars(
            select(CfgItem).where(CfgItem.cr_norm == cr).order_by(CfgItem.ordem, CfgItem.id)
        ).all()
        return {
            "itens": itens,
            "alvo_contratual": alvo_contratual(contrato),
            "soma_itens": float(sum((i.custo_alvo or 0) for i in itens)),
        }
    if aba == "depara":
        itens = sessao.scalars(
            select(CfgItem).where(CfgItem.cr_norm == cr).order_by(CfgItem.ordem)
        ).all()
        naturezas = naturezas_do_cr(sessao, cr)
        total = sum(n["total"] for n in naturezas)
        classificado = sum(n["total"] for n in naturezas if n["item"])
        return {
            "itens": itens,
            "naturezas": naturezas,
            "cobertura": classificado / total if total else 1.0,
        }
    if aba == "bms":
        return {"nfs": nfs_do_cr(sessao, cr)}
    if aba == "pendencias":
        return {
            "pendencias": sessao.scalars(
                select(CfgPendencia)
                .where(CfgPendencia.cr_norm == cr)
                .order_by(CfgPendencia.prazo.asc().nulls_last())
            ).all()
        }
    if aba == "pleitos":
        return {
            "pleitos": sessao.scalars(
                select(CfgPleito)
                .where(CfgPleito.cr_norm == cr)
                .order_by(CfgPleito.data_base.desc().nulls_last())
            ).all()
        }
    if aba == "parametros":
        return {"parametros": sessao.get(Parametros, cr)}
    return {}


def _voltar(cr: str, aba: str):
    return redirect(url_for("configuracao.lista", cr=cr, aba=aba))


@bp.post("/<cr>/<aba>")
@requer("operador")
def salvar(cr: str, aba: str):
    contrato = contrato_por_cr(db.session, cr_norm(cr))
    if contrato is None or aba not in dict(ABAS):
        abort(404)
    if not contrato.receita and aba not in ABAS_SEM_RECEITA:
        flash(
            "Este CR só existe no Controle de Despesa: só o de-para pode ser configurado.", "erro"
        )
        return _voltar(contrato.cr, "depara")
    usuario = usuario_atual()
    try:
        contagem = _salvar_aba(contrato, aba, request.form, usuario.id)
    except (ErroDeValidacao, ValueError) as erro:
        db.session.rollback()
        flash(f"Nada foi salvo. {erro}", "erro")
        return _voltar(contrato.cr, aba)
    if contagem.mudou:
        registrar(
            db.session,
            acao=f"configuracao.{aba}",
            usuario=usuario,
            alvo_tipo="contrato",
            payload={"cr": contrato.cr, **contagem.como_dict()},
        )
    db.session.commit()
    flash("Alterações salvas." if contagem.mudou else "Nada mudou.", "")
    return _voltar(contrato.cr, aba)


def _salvar_aba(contrato, aba: str, form, usuario_id: int) -> gravar.Contagem:
    sessao, cr = db.session, contrato.cr
    if aba == "prazos":
        return gravar.salvar_prazos(
            sessao, cr, data_br(form.get("fim_execucao"), "Fim da execução"), usuario_id
        )
    if aba == "parametros":
        if form.get("padrao"):
            return gravar.salvar_parametros(sessao, cr, None, None, usuario_id)
        tributos = decimal_br(form.get("tributos"), "Tributos", obrigatorio=True) / 100
        taxa = decimal_br(form.get("taxa_adm"), "Taxa adm.", obrigatorio=True) / 100
        return gravar.salvar_parametros(sessao, cr, tributos, taxa, usuario_id)
    if aba == "itens":
        linhas = []
        for n, linha in enumerate(linhas_do_form(form, "it"), start=1):
            if linha.get("remover") or not (
                linha.get("codigo", "").strip() or linha.get("descricao", "").strip()
            ):
                continue
            if not linha.get("codigo", "").strip() or not linha.get("descricao", "").strip():
                raise ErroDeValidacao(f"Item na linha {n}: código e descrição são obrigatórios")
            linhas.append(_item(linha, f"Item {linha['codigo']}"))
        return gravar.substituir_itens(sessao, cr, linhas, usuario_id)
    if aba == "depara":
        mapa = {
            linha["natureza"]: linha.get("item", "")
            for linha in linhas_do_form(form, "dp")
            if linha.get("natureza")
        }
        return gravar.salvar_depara(sessao, cr, mapa, usuario_id)
    if aba == "bms":
        linhas = []
        for linha in linhas_do_form(form, "bm"):
            numero = decimal_br(linha.get("numero"), "BM")
            linhas.append(
                {
                    "nf_origem_id": int(linha["nf"]),
                    "numero": int(numero) if numero is not None else None,
                    "data_base": mes_br(linha.get("data_base"), "Data-base"),
                }
            )
        return gravar.salvar_bms(sessao, cr, linhas, usuario_id)
    if aba == "pendencias":
        linhas = [
            _pendencia(linha)
            for linha in linhas_do_form(form, "pd")
            if not linha.get("remover") and linha.get("assunto", "").strip()
        ]
        return gravar.substituir_pendencias(sessao, cr, linhas, usuario_id)
    if aba == "pleitos":
        linhas = [
            _pleito(linha)
            for linha in linhas_do_form(form, "pl")
            if not linha.get("remover") and linha.get("descricao", "").strip()
        ]
        return gravar.substituir_pleitos(sessao, cr, linhas, usuario_id)
    abort(404)


def _item(linha: dict, rotulo: str) -> dict:
    return {
        "codigo": str(linha.get("codigo")).strip()[:20],
        "descricao": str(linha.get("descricao")).strip()[:300],
        "unidade": str(linha.get("unidade") or "").strip()[:20],
        "quantidade": decimal_br(linha.get("quantidade"), f"{rotulo}: quantidade"),
        "custo_alvo": decimal_br(linha.get("custo_alvo"), f"{rotulo}: custo-alvo") or Decimal("0"),
        "custo_alvo_projetado": decimal_br(
            linha.get("custo_alvo_projetado"), f"{rotulo}: custo-alvo projetado"
        ),
        "quantidade_medida": decimal_br(
            linha.get("quantidade_medida"), f"{rotulo}: quantidade medida"
        ),
    }


def _pendencia(linha: dict) -> dict:
    return {
        "assunto": str(linha.get("assunto")).strip(),
        "prazo": data_br(linha.get("prazo"), "Prazo"),
        "prioridade": opcao(linha.get("prioridade"), "Prioridade", PRIORIDADES, "MÉDIA"),
        "status": opcao(linha.get("status"), "Status", STATUS_PENDENCIA, "ABERTA"),
    }


def _pleito(linha: dict) -> dict:
    return {
        "data_base": mes_br(linha.get("data_base"), "Data-base"),
        "descricao": str(linha.get("descricao")).strip(),
        "tipo": opcao(linha.get("tipo"), "Tipo", TIPOS_PLEITO, "ADITIVO"),
        "status": opcao(linha.get("status"), "Status", STATUS_PLEITO, "SOLICITAR"),
        "valor": decimal_br(linha.get("valor"), "Valor") or Decimal("0"),
        "observacao": (str(linha.get("observacao") or "").strip() or None),
    }


# --- planilha -----------------------------------------------------------------------


@bp.get("/modelo.xlsx")
@requer("operador")
def modelo():
    return send_file(
        planilha.gerar(db.session, crs=[]),
        as_attachment=True,
        download_name="controle-financeiro-modelo-configuracao.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.get("/<cr>/planilha.xlsx")
@requer("operador")
def planilha_do_cr(cr: str):
    contrato = contrato_por_cr(db.session, cr_norm(cr))
    if contrato is None:
        abort(404)
    return send_file(
        planilha.gerar(db.session, crs=[contrato.cr]),
        as_attachment=True,
        download_name=f"controle-financeiro-config-{contrato.cr}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.get("/importar")
@requer("operador")
def importar():
    return render_template("configuracao/importar.html", secao="configuracao")


@bp.post("/importar")
@requer("operador")
@limiter.limit("20 per minute")
def previa():
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename.lower().endswith(".xlsx"):
        flash("Escolha uma planilha .xlsx (use o modelo baixado do sistema).", "erro")
        return redirect(url_for("configuracao.importar"))
    conteudo = arquivo.read()
    sha = hashlib.sha256(conteudo).hexdigest()
    PASTA_IMPORT.mkdir(parents=True, exist_ok=True)
    (PASTA_IMPORT / f"{sha}.xlsx").write_bytes(conteudo)
    resultado = planilha.aplicar(
        db.session, PASTA_IMPORT / f"{sha}.xlsx", usuario_atual().id, simular=True
    )
    db.session.rollback()
    return render_template(
        "configuracao/previa.html",
        secao="configuracao",
        r=resultado,
        sha=sha,
        nome=arquivo.filename,
    )


@bp.post("/importar/confirmar")
@requer("operador")
def confirmar():
    sha = request.form.get("sha", "")
    caminho = PASTA_IMPORT / f"{sha}.xlsx"
    if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha) or not caminho.is_file():
        flash("A prévia expirou. Envie a planilha de novo.", "erro")
        return redirect(url_for("configuracao.importar"))
    usuario = usuario_atual()
    resultado = planilha.aplicar(db.session, caminho, usuario.id, simular=False)
    if resultado.erros:
        db.session.rollback()
        flash("A planilha tem erros; nada foi gravado.", "erro")
        return redirect(url_for("configuracao.importar"))
    db.session.add(
        ConfigImportacao(
            arquivo=request.form.get("nome", "planilha.xlsx")[:255],
            sha256=sha,
            usuario_id=usuario.id,
            contagens=resultado.contagens_dict(),
            avisos=resultado.avisos[:200],
        )
    )
    registrar(
        db.session,
        acao="configuracao.importacao",
        usuario=usuario,
        alvo_tipo="planilha",
        payload={"crs": ", ".join(resultado.crs), **resultado.totais().como_dict()},
    )
    db.session.commit()
    caminho.unlink(missing_ok=True)
    flash(f"Planilha importada: {', '.join(resultado.crs) or 'nenhum CR'} atualizado(s).", "")
    return redirect(url_for("configuracao.lista", cr=resultado.crs[0] if resultado.crs else None))
