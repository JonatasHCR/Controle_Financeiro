"""Captura a página de impressão (PNG) e gera o PDF, como o sistema faz.

Uso (dentro do container web, com o app no ar em 127.0.0.1:8000):
    python scripts/captura_tela.py "cr=4501" /tmp/saida
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlencode

from itsdangerous import URLSafeTimedSerializer
from playwright.sync_api import sync_playwright
from sqlalchemy import select

from app.extensions import db
from app.factory import create_app
from app.models import Usuario


def main(consulta: str, destino: str) -> None:
    app = create_app()
    with app.app_context():
        usuario = db.session.scalars(
            select(Usuario).where(Usuario.email == "captura@local")
        ).first()
        if usuario is None:
            usuario = Usuario(nome="Captura de tela", email="captura@local", perfil="admin")
            db.session.add(usuario)
            db.session.commit()
        token = URLSafeTimedSerializer(app.secret_key, salt="relatorio-impressao").dumps(
            {"u": usuario.id, "q": consulta}
        )
        url = f"{app.config['PDF_BASE_URL']}/relatorio/impressao?{urlencode({'t': token})}"

    saida = Path(destino)
    saida.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        navegador = p.chromium.launch(args=["--no-sandbox"])
        pagina = navegador.new_page(viewport={"width": 1240, "height": 900}, locale="pt-BR")
        erros = []
        pagina.on("pageerror", lambda e: erros.append(str(e)))
        pagina.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
        pagina.goto(url, wait_until="networkidle")
        pagina.wait_for_function("window.__graficosProntos === true", timeout=20_000)
        pagina.screenshot(path=str(saida / "pagina.png"), full_page=True)
        (saida / "relatorio.pdf").write_bytes(
            pagina.pdf(format="A4", landscape=True, print_background=True)
        )
        navegador.close()
    print("erros no navegador:", erros or "nenhum")


if __name__ == "__main__":
    main(
        sys.argv[1] if len(sys.argv) > 1 else "",
        sys.argv[2] if len(sys.argv) > 2 else "/tmp/captura",
    )
