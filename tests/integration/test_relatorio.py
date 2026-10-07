"""PDF gerado pelo sistema e a página de impressão que ele usa."""

from __future__ import annotations

import os
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.models import Auditoria
from app.relatorio import rotas

pytestmark = pytest.mark.integration


@pytest.fixture
def pdf_falso(monkeypatch):
    chamadas = []

    def gerar(url):
        chamadas.append(url)
        return b"%PDF-1.7 falso"

    monkeypatch.setattr(rotas, "gerar_pdf", gerar)
    return chamadas


def test_pdf_exige_login(client):
    assert client.get("/relatorio/pdf").status_code == 302


def test_pdf_baixa_com_nome_e_auditoria(entrar, leitor, carregado, pdf_falso, db):
    resposta = entrar(leitor).get("/relatorio/pdf?cr=4561&modo=mes&mes=2026-02")
    assert resposta.status_code == 200
    assert resposta.mimetype == "application/pdf"
    assert resposta.data.startswith(b"%PDF")
    assert (
        'filename="relatorio-financeiro_4561_2026-02.pdf"' in resposta.headers["Content-Disposition"]
    )
    assert db.session.scalars(select(Auditoria).where(Auditoria.acao == "relatorio.pdf")).one()


def test_impressao_abre_com_o_token_e_os_mesmos_filtros(
    app, entrar, leitor, carregado, pdf_falso, client
):
    entrar(leitor).get("/relatorio/pdf?cr=4561")
    url = urlsplit(pdf_falso[0])
    token = parse_qs(url.query)["t"][0]
    with client.session_transaction() as sessao:
        sessao.clear()
    corpo = client.get(f"/relatorio/impressao?t={token}").get_data(as_text=True)
    assert 'class="pre impressao"' in corpo
    assert '"cr": "4561"' in corpo or '"cr":"4561"' in corpo


def test_impressao_sem_token_valido_e_recusada(client):
    assert client.get("/relatorio/impressao?t=forjado").status_code == 403


def test_falha_do_chromium_vira_erro_legivel(entrar, leitor, carregado, monkeypatch):
    def quebra(url):
        raise RuntimeError("sem chromium")

    monkeypatch.setattr(rotas, "gerar_pdf", quebra)
    resposta = entrar(leitor).get("/relatorio/pdf")
    assert resposta.status_code == 500
    assert "Não foi possível gerar o PDF" in resposta.get_data(as_text=True)


@pytest.mark.skipif(
    not os.environ.get("RODAR_PDF_REAL"), reason="defina RODAR_PDF_REAL=1 com o servidor no ar"
)
def test_pdf_real_com_chromium(entrar, leitor, carregado):
    resposta = entrar(leitor).get("/relatorio/pdf")
    assert resposta.data.startswith(b"%PDF")
