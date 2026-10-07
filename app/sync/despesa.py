"""Espelho do Controle de Despesa.

Centros, fornecedores e naturezas vêm inteiros. Despesas são incrementais; as
exclusões vêm da trigger do Controle, e a conferência por /status + /ids pega o
que escapar (restauração de backup lá, por exemplo).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.analise.normalizar import cr_norm, nome_norm
from app.models import CdCentro, CdDespesa, CdFornecedor, CdNatureza
from app.sync.marcas import marca
from app.sync.upsert import apagar, apagar_ausentes, upsert

FONTE = "controle"
SOBREPOSICAO = timedelta(minutes=10)


def _data(valor) -> date | None:
    return date.fromisoformat(valor) if valor else None


def _instante(valor) -> datetime | None:
    return datetime.fromisoformat(valor.replace("Z", "+00:00")) if valor else None


def _dec(valor) -> Decimal | None:
    return None if valor is None else Decimal(str(valor))


def _dominios(session, cliente) -> dict:
    centros = cliente.get("centros_custo")["centros_custo"]
    upsert(
        session,
        CdCentro,
        [
            {
                "origem_id": c["id"],
                "codigo": c["codigo"],
                "cr_norm": cr_norm(c["codigo"]),
                "nome": c.get("nome") or "",
            }
            for c in centros
        ],
    )
    apagar_ausentes(session, CdCentro, {c["id"] for c in centros})

    fornecedores = cliente.get("fornecedores")["fornecedores"]
    upsert(session, CdFornecedor, [{"origem_id": f["id"], "nome": f["nome"]} for f in fornecedores])
    apagar_ausentes(session, CdFornecedor, {f["id"] for f in fornecedores})

    naturezas = cliente.get("naturezas")["naturezas"]
    upsert(
        session,
        CdNatureza,
        [
            {"origem_id": n["id"], "nome": n["nome"], "nome_norm": nome_norm(n["nome"])}
            for n in naturezas
        ],
    )
    apagar_ausentes(session, CdNatureza, {n["id"] for n in naturezas})
    return {"centros": len(centros), "fornecedores": len(fornecedores), "naturezas": len(naturezas)}


def _linha(d: dict) -> dict:
    return {
        "origem_id": d["id"],
        "centro_origem_id": d["centro_custo_id"],
        "fornecedor_origem_id": d["fornecedor_id"],
        "natureza_origem_id": d["natureza_id"],
        "data_baixa": _data(d.get("data_baixa")),
        "data_emissao": _data(d.get("data_emissao")),
        "valor_original": _dec(d.get("valor_original")),
        "valor_baixado": _dec(d.get("valor_baixado")),
        "referencia": d.get("referencia"),
        "documento": d.get("documento") or "",
        "historico": d.get("historico") or "",
        "origem_atualizado_em": _instante(d.get("atualizado_em")),
    }


def _despesas(session, cliente, completo: bool) -> int:
    registro = marca(session, FONTE, "despesas")
    desde = (
        None if completo or registro.marca_dados is None else registro.marca_dados - SOBREPOSICAO
    )
    vistos, nova = set(), registro.marca_dados
    for pagina, watermark in cliente.paginar(
        "despesas", "despesas", limite=2000, updated_since=desde.isoformat() if desde else None
    ):
        upsert(session, CdDespesa, [_linha(d) for d in pagina])
        vistos |= {d["id"] for d in pagina}
        if watermark:
            nova = max(filter(None, [nova, _instante(watermark)]))
    if completo:
        apagar_ausentes(session, CdDespesa, vistos)
        registro.ultima_completa_em = func.now()
    registro.marca_dados = nova
    return len(vistos)


def _exclusoes(session, cliente) -> int:
    registro = marca(session, FONTE, "despesas")
    total, nova = 0, registro.marca_exclusoes
    # Folga como nas despesas: uma limpeza longa no Controle grava a hora do
    # início da transação, mas só aparece no fim.
    desde = registro.marca_exclusoes - SOBREPOSICAO if registro.marca_exclusoes else None
    for pagina, watermark in cliente.paginar(
        "despesas/exclusoes",
        "exclusoes",
        marca="since",
        since=desde.isoformat() if desde else None,
    ):
        total += apagar(session, CdDespesa, [x["id"] for x in pagina])
        if watermark:
            nova = max(filter(None, [nova, _instante(watermark)]))
    registro.marca_exclusoes = nova
    return total


def sincronizar(session, cliente, completo: bool = False) -> dict:
    contagens = _dominios(session, cliente)
    contagens["despesas"] = _despesas(session, cliente, completo)
    contagens["exclusoes"] = _exclusoes(session, cliente)
    session.flush()

    status = cliente.get("status")["despesas"]
    esperado = status["count"]
    if _contagem(session) != esperado:
        ids = set(cliente.get("despesas/ids")["ids"])
        contagens["reconciliado"] = apagar_ausentes(session, CdDespesa, ids)
        session.flush()
        if _contagem(session) != esperado:
            contagens["despesas"] = _despesas(session, cliente, completo=True)
            session.flush()

    # A quantidade não vê um valor alterado que escapou; a soma vê.
    soma = status.get("sum_valor_baixado")
    if soma is not None and _soma(session) != Decimal(str(soma)):
        contagens["despesas"] = _despesas(session, cliente, completo=True)
        contagens["reconciliado_soma"] = True
    return contagens


def _contagem(session) -> int:
    return session.scalar(select(func.count()).select_from(CdDespesa))


def _soma(session) -> Decimal:
    return Decimal(str(session.scalar(select(func.coalesce(func.sum(CdDespesa.valor_baixado), 0)))))
