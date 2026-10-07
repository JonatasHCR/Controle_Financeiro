"""Painel: a página e o JSON que ela consome ao trocar de filtro."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from app.analise.painel import montar_painel
from app.analise.periodo import Filtro
from app.auth.guardas import login_obrigatorio, usuario_atual
from app.extensions import db

bp = Blueprint("painel", __name__)


@bp.get("/")
@login_obrigatorio
def pagina():
    dados = montar_painel(db.session, Filtro.da_query(request.args), usuario_atual())
    return render_template("painel/pagina.html", secao="painel", dados=dados, impressao=False)


@bp.get("/api/painel")
@login_obrigatorio
def api():
    return jsonify(montar_painel(db.session, Filtro.da_query(request.args), usuario_atual()))
