"""Exercita a tela interativa num Chromium real (filtros, período, busca, PDF).

Só para desenvolvimento: abre uma sessão pelo test_client do Flask (sem
Keycloak) e passa o cookie ao navegador. Rode dentro do container web:
    python scripts/testar_tela.py /tmp/tela
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from sqlalchemy import select

from app.extensions import db
from app.factory import create_app
from app.models import Usuario


def cookie_de_sessao(app) -> tuple[str, str]:
    with app.app_context():
        usuario = db.session.scalars(
            select(Usuario).where(Usuario.email == "captura@local")
        ).first()
        if usuario is None:
            usuario = Usuario(nome="Captura de tela", email="captura@local", perfil="admin")
            db.session.add(usuario)
            db.session.commit()
        identificador = usuario.id
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao["usuario_id"] = identificador
        sessao["grupos"] = ["/apps/controle-financeiro", "/apps/receita"]
    nome = app.config["SESSION_COOKIE_NAME"]
    return nome, cliente.get_cookie(nome).value


def main(destino: str) -> None:
    app = create_app()
    base = app.config["PDF_BASE_URL"]
    nome, valor = cookie_de_sessao(app)
    saida = Path(destino)
    saida.mkdir(parents=True, exist_ok=True)
    erros, passos = [], []

    with sync_playwright() as p:
        navegador = p.chromium.launch(args=["--no-sandbox"])
        contexto = navegador.new_context(
            viewport={"width": 1366, "height": 900}, locale="pt-BR", accept_downloads=True
        )
        contexto.add_cookies([{"name": nome, "value": valor, "url": base}])
        pagina = contexto.new_page()
        pagina.on("pageerror", lambda e: erros.append(f"pageerror: {e}"))
        pagina.on(
            "console", lambda m: erros.append(f"console: {m.text}") if m.type == "error" else None
        )

        pagina.goto(f"{base}/", wait_until="networkidle")
        passos.append(f"abriu: {pagina.title()}")
        pagina.screenshot(path=str(saida / "1-inicial.png"))

        # busca + marcar um CR no filtro de centro de custo
        pagina.click("#f-cr summary")
        pagina.fill("#f-cr .busca", "4501")
        visiveis = pagina.locator("#f-cr .lista label:not([hidden])").count()
        passos.append(f"busca '4501' deixou {visiveis} opção(ões)")
        pagina.press("#f-cr .busca", "Enter")
        pagina.wait_for_load_state("networkidle")
        pagina.wait_for_timeout(400)
        passos.append(f"contexto: {pagina.inner_text('#context')}")
        passos.append(f"url: {pagina.url}")

        # período: só o mês (sem mês escolhido vai para o mais recente)
        pagina.click("body")
        pagina.click("[data-modo=mes]")
        pagina.wait_for_load_state("networkidle")
        pagina.wait_for_timeout(400)
        passos.append(
            f"só o mês -> {pagina.inner_text('#context')} | mês: {pagina.input_value('#f-mes')}"
        )

        # intervalo de datas: inicial não passa da final
        pagina.click("[data-modo=intervalo]")
        pagina.wait_for_load_state("networkidle")
        pagina.wait_for_timeout(400)
        passos.append(
            f"intervalo -> de={pagina.input_value('#f-de')} até={pagina.input_value('#f-ate')} "
            f"(max do 'de' = {pagina.get_attribute('#f-de', 'max')})"
        )
        pagina.screenshot(path=str(saida / "2-filtrado.png"), full_page=True)

        # PDF gerado pelo sistema
        pagina.click("#bt-pdf")
        with pagina.expect_download(timeout=60_000) as baixou:
            pagina.click("#pdf-go")
        arquivo = baixou.value
        arquivo.save_as(saida / arquivo.suggested_filename)
        tamanho = (saida / arquivo.suggested_filename).stat().st_size
        passos.append(f"PDF baixado: {arquivo.suggested_filename} ({tamanho} bytes)")
        pagina.screenshot(path=str(saida / "3-pdf.png"))

        # limpar filtros
        pagina.click("#modal-x")
        pagina.click("#bt-limpar")
        pagina.wait_for_load_state("networkidle")
        pagina.wait_for_timeout(400)
        passos.append(f"limpar -> url: {pagina.url} | {pagina.inner_text('#context')}")

        for nome_arq, caminho in (
            ("4-config-itens", "/configuracao/?cr=4501&aba=itens"),
            ("5-config-depara", "/configuracao/?cr=1950&aba=depara"),
            ("6-admin", "/administracao/"),
            ("7-auditoria", "/auditoria/"),
        ):
            pagina.goto(f"{base}{caminho}", wait_until="networkidle")
            pagina.screenshot(path=str(saida / f"{nome_arq}.png"), full_page=True)
            passos.append(f"{caminho}: {pagina.title()}")
        navegador.close()

    print("\n".join(passos))
    print("erros no navegador:", erros or "nenhum")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/tela")
