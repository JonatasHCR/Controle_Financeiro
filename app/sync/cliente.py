"""Cliente das APIs /api/v1 da Receita e do Controle de Despesa."""

from __future__ import annotations

from collections.abc import Iterator

import requests


class ErroDeSync(Exception):
    pass


class ClienteApi:
    def __init__(
        self, base: str, token: str, timeout: int = 30, sessao: requests.Session | None = None
    ):
        if not base or not token:
            raise ErroDeSync("URL ou token da API não configurados")
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.http = sessao or requests.Session()
        self.http.headers["Authorization"] = f"Bearer {token}"

    def get(self, caminho: str, **params) -> dict:
        url = f"{self.base}/{caminho.lstrip('/')}"
        try:
            resposta = self.http.get(
                url, params={k: v for k, v in params.items() if v is not None}, timeout=self.timeout
            )
        except requests.RequestException as erro:
            raise ErroDeSync(f"{url}: {erro}") from erro
        if resposta.status_code != 200:
            raise ErroDeSync(f"{url}: HTTP {resposta.status_code}")
        return resposta.json()

    def paginar(
        self, caminho: str, chave: str, limite: int = 1000, **params
    ) -> Iterator[list[dict]]:
        """Página a página até has_more=false. Devolve também a marca d'água da última."""
        offset = 0
        while True:
            corpo = self.get(caminho, limit=limite, offset=offset, **params)
            itens = corpo.get(chave, [])
            yield itens, corpo.get("watermark")
            if not corpo.get("has_more") or not itens:
                return
            offset += len(itens)
