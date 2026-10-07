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
        self, caminho: str, chave: str, limite: int = 1000, marca: str = "updated_since", **params
    ) -> Iterator[list[dict]]:
        """Página a página até has_more=false. Devolve também a marca d'água da última.

        Com `last_id` na resposta, a próxima página parte da última linha lida
        (`marca` + `after_id`); sem ele, cai no offset. Página repetida é erro:
        sem essa trava, uma API que ignora a paginação prende o sync num laço.
        """
        offset, cursor, anterior = 0, None, None
        while True:
            consulta = {**params, **cursor} if cursor else {**params, "offset": offset}
            corpo = self.get(caminho, limit=limite, **consulta)
            itens = corpo.get(chave, [])
            yield itens, corpo.get("watermark")
            if not corpo.get("has_more") or not itens:
                return

            assinatura = (corpo.get("watermark"), corpo.get("last_id"), len(itens), str(itens[-1]))
            if assinatura == anterior:
                raise ErroDeSync(f"{caminho}: a API devolveu a mesma página de novo")
            anterior = assinatura

            if corpo.get("last_id") is not None and corpo.get("watermark"):
                cursor = {marca: corpo["watermark"], "after_id": corpo["last_id"]}
            else:
                offset += len(itens)
