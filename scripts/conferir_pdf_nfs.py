"""Confere que o PDF lista todas as NFs (banco de teste, sem servidor no ar).

Uso, dentro do container web com o db-test de pé:
    APP_CONFIG=test python scripts/conferir_pdf_nfs.py /tmp/saida
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from itsdangerous import URLSafeTimedSerializer
from playwright.sync_api import sync_playwright
from sqlalchemy import select

from app.extensions import db
from app.factory import create_app
from app.models import RcContrato, RcNf, Usuario
from tests.integration.semente import semear

QUANTAS = 80
BASE = "http://relatorio.local"


def main(destino: str) -> None:
    app = create_app("test")
    saida = Path(destino)
    saida.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        db.drop_all()
        db.create_all()
        semear(db.session)
        contrato = db.session.scalars(select(RcContrato).where(RcContrato.cr_norm == "4561")).one()
        for n in range(QUANTAS):
            db.session.add(
                RcNf(
                    origem_id=10_000 + n,
                    contrato_origem_id=contrato.origem_id,
                    numero=f"9{n:03d}",
                    emitida_em=date(2025, 1, 1) + timedelta(days=5 * n),
                    valor=Decimal("1000"),
                )
            )
        usuario = Usuario(nome="Conferência", email="conferencia@local", perfil="admin")
        db.session.add(usuario)
        db.session.commit()
        token = URLSafeTimedSerializer(app.secret_key, salt="relatorio-impressao").dumps(
            {"u": usuario.id, "q": "cr=4561"}
        )

        cliente = app.test_client()

        def responder(rota):
            partes = urlsplit(rota.request.url)
            caminho = partes.path + (f"?{partes.query}" if partes.query else "")
            resposta = cliente.get(caminho)
            rota.fulfill(
                status=resposta.status_code,
                headers={"Content-Type": resposta.content_type},
                body=resposta.get_data(),
            )

        with sync_playwright() as p:
            navegador = p.chromium.launch(args=["--no-sandbox"])
            pagina = navegador.new_page(viewport={"width": 1240, "height": 900}, locale="pt-BR")
            pagina.route(f"{BASE}/**", responder)
            pagina.goto(f"{BASE}/relatorio/impressao?{urlencode({'t': token})}")
            pagina.wait_for_function("window.__graficosProntos === true", timeout=20_000)
            linhas = pagina.locator("#tb-nf tbody tr").count()
            pagina.emulate_media(media="print")
            visivel = pagina.evaluate(
                "() => { const w = document.querySelector('#tb-nf');"
                " return [w.clientHeight, w.scrollHeight]; }"
            )
            pdf = pagina.pdf(format="A4", landscape=True, print_background=True)
            (saida / "relatorio.pdf").write_bytes(pdf)
            pagina.locator("#tb-nf").screenshot(path=str(saida / "nfs.png"))
            navegador.close()

        print(f"NFs na tabela: {linhas} | caixa na impressão (visível/total): {visivel}")
        print(f"páginas do PDF: {pdf.count(b'/Type /Page') - pdf.count(b'/Type /Pages')}")
        db.session.remove()
        db.drop_all()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/conferir_pdf")
