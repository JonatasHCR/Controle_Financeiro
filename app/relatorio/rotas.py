"""Relatório em PDF gerado pelo próprio sistema.

O Chromium (Playwright) abre a página de impressão — a mesma do painel, com os
gráficos Chart.js — e salva em A4 paisagem. Ele não tem a sessão de quem pediu,
então entra com um token assinado que vale dois minutos.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode

from flask import Blueprint, Response, abort, current_app, render_template, request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.datastructures import MultiDict

from app.analise.painel import montar_painel
from app.analise.periodo import Filtro
from app.auditoria.servico import registrar
from app.auth.guardas import login_obrigatorio, usuario_atual
from app.extensions import csrf, db, limiter
from app.models import Usuario

bp = Blueprint("relatorio", __name__, url_prefix="/relatorio")

VALIDADE_TOKEN = 120


def _assinador() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt="relatorio-impressao")


def _nome_arquivo(dados: dict) -> str:
    crs = [c["cr"] for c in dados["contratos"]]
    parte = crs[0] if len(crs) == 1 else (f"{len(crs)}-contratos" if crs else "vazio")
    return f"relatorio-financeiro_{parte}_{dados['meta']['corte']}.pdf"


def gerar_pdf(url: str) -> bytes:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch(args=["--no-sandbox"])
        try:
            pagina = navegador.new_page(viewport={"width": 1240, "height": 900}, locale="pt-BR")
            pagina.goto(url, wait_until="networkidle", timeout=30_000)
            pagina.wait_for_function("window.__graficosProntos === true", timeout=20_000)
            return pagina.pdf(
                format="A4",
                landscape=True,
                print_background=True,
                margin={"top": "10mm", "bottom": "10mm", "left": "10mm", "right": "10mm"},
            )
        finally:
            navegador.close()


@bp.get("/pdf")
@login_obrigatorio
@limiter.limit("10 per minute")
def pdf():
    usuario = usuario_atual()
    consulta = request.query_string.decode()
    dados = montar_painel(db.session, Filtro.da_query(request.args), usuario)
    token = _assinador().dumps({"u": usuario.id, "q": consulta})
    url = f"{current_app.config['PDF_BASE_URL']}/relatorio/impressao?{urlencode({'t': token})}"
    try:
        conteudo = gerar_pdf(url)
    except Exception as erro:  # Chromium ausente, timeout etc.
        current_app.logger.exception("falha ao gerar PDF", exc_info=erro)
        return Response("Não foi possível gerar o PDF.", status=500, mimetype="text/plain")

    registrar(
        db.session,
        acao="relatorio.pdf",
        usuario=usuario,
        alvo_tipo="relatorio",
        payload={
            "contratos": dados["meta"]["rotulos"]["contratos"],
            "periodo": dados["meta"]["periodo"],
        },
    )
    db.session.commit()
    nome = _nome_arquivo(dados)
    return Response(
        conteudo,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@bp.get("/impressao")
@csrf.exempt
@limiter.exempt
def impressao():
    try:
        carga = _assinador().loads(request.args.get("t", ""), max_age=VALIDADE_TOKEN)
    except BadSignature:
        abort(403)
    usuario = db.session.get(Usuario, carga.get("u"))
    if usuario is None or not usuario.ativo:
        abort(403)
    args = MultiDict([(k, v) for k, vs in parse_qs(carga.get("q", "")).items() for v in vs])
    dados = montar_painel(db.session, Filtro.da_query(args), usuario)
    return render_template("painel/pagina.html", dados=dados, impressao=True)
