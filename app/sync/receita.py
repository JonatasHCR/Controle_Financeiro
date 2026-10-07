"""Espelho do Gerenciamento de Receita.

Tabelas pequenas (clientes, contratos, aditivos, previsões) vêm inteiras a
cada rodada. NFs e recebimentos são incrementais, com exclusões pelo PaperTrail
e conferência de contagem contra /status.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.analise.normalizar import cr_norm, nome_norm
from app.models import (
    RcAjuste,
    RcCliente,
    RcContrato,
    RcContratoCoordenador,
    RcNf,
    RcPrevisao,
    RcRecebimento,
)
from app.sync.marcas import marca, salvar_marca
from app.sync.upsert import apagar, apagar_ausentes, upsert

FONTE = "receita"
SOBREPOSICAO = timedelta(minutes=10)

MESES = {
    "JANEIRO": 1,
    "FEVEREIRO": 2,
    "MARÇO": 3,
    "MARCO": 3,
    "ABRIL": 4,
    "MAIO": 5,
    "JUNHO": 6,
    "JULHO": 7,
    "AGOSTO": 8,
    "SETEMBRO": 9,
    "OUTUBRO": 10,
    "NOVEMBRO": 11,
    "DEZEMBRO": 12,
}


def _data(valor) -> date | None:
    return date.fromisoformat(valor) if valor else None


def _instante(valor) -> datetime | None:
    return datetime.fromisoformat(valor.replace("Z", "+00:00")) if valor else None


def _dec(valor) -> Decimal | None:
    return None if valor is None else Decimal(str(valor))


def competencia(mes_ano: str | None) -> date | None:
    """'JUNHO/2026' → 2026-06-01."""
    try:
        mes, ano = (mes_ano or "").upper().split("/")
        return date(int(ano), MESES[mes.strip()], 1)
    except (ValueError, KeyError):
        return None


def _tudo(cliente, caminho: str, chave: str) -> list[dict]:
    return [item for pagina, _ in cliente.paginar(caminho, chave) for item in pagina]


def _clientes(session, cliente) -> int:
    itens = _tudo(cliente, "clients", "clients")
    upsert(
        session,
        RcCliente,
        [
            {
                "origem_id": c["id"],
                "nome": c.get("name") or "",
                "nome_completo": c.get("full_name") or "",
                "origem_atualizado_em": _instante(c.get("updated_at")),
            }
            for c in itens
        ],
    )
    apagar_ausentes(session, RcCliente, {c["id"] for c in itens})
    return len(itens)


def _contratos(session, cliente) -> int:
    itens = _tudo(cliente, "cost_centers", "cost_centers")
    upsert(
        session,
        RcContrato,
        [
            {
                "origem_id": c["id"],
                "cr_code": c["cr_code"],
                "cr_norm": cr_norm(c["cr_code"]),
                "descricao": c.get("description") or "",
                "numero_contrato": c.get("contract_number"),
                "coordenador": c.get("coordinator"),
                "objeto": c.get("object_text"),
                "cliente_origem_id": c.get("client_id"),
                "valor": _dec(c.get("value")),
                "participacao": _dec(c.get("participation")),
                "data_inicio": _data(c.get("start_date")),
                "data_fim": _data(c.get("end_date")),
                "origem_atualizado_em": _instante(c.get("updated_at")),
            }
            for c in itens
        ],
    )
    ids = {c["id"] for c in itens}
    apagar_ausentes(session, RcContrato, ids)

    # coordenadores: refeitos a cada rodada
    session.execute(delete(RcContratoCoordenador))
    linhas, vistos = [], set()
    for c in itens:
        for nome in c.get("coordinator_list") or []:
            chave = (c["id"], nome_norm(nome))
            if nome.strip() and chave not in vistos:
                vistos.add(chave)
                linhas.append(
                    RcContratoCoordenador(
                        contrato_origem_id=c["id"], nome=nome.strip(), nome_norm=chave[1]
                    )
                )
    session.add_all(linhas)
    return len(itens)


def _ajustes(session, cliente) -> int:
    itens = _tudo(cliente, "adjustments", "adjustments")
    upsert(
        session,
        RcAjuste,
        [
            {
                "origem_id": a["id"],
                "contrato_origem_id": a["cost_center_id"],
                "tipo": a.get("kind") or "valor",
                "valor_anterior": _dec(a.get("previous_value")),
                "valor_novo": _dec(a.get("new_value")),
                "data_anterior": _data(a.get("previous_date")),
                "data_nova": _data(a.get("new_date")),
                "nota": a.get("note"),
                "criado_origem_em": _instante(a.get("created_at")),
                "origem_atualizado_em": _instante(a.get("updated_at")),
            }
            for a in itens
        ],
    )
    apagar_ausentes(session, RcAjuste, {a["id"] for a in itens})
    return len(itens)


def _previsoes(session, cliente) -> int:
    itens = _tudo(cliente, "forecast_entries", "forecast_entries")
    upsert(
        session,
        RcPrevisao,
        [
            {
                "origem_id": f["id"],
                "contrato_origem_id": f["cost_center_id"],
                "competencia": competencia(f.get("month_year")),
                "valor_previsto": _dec(f.get("forecasted_total")),
                "origem_atualizado_em": _instante(f.get("updated_at")),
            }
            for f in itens
        ],
    )
    apagar_ausentes(session, RcPrevisao, {f["id"] for f in itens})
    return len(itens)


def _linha_nf(n: dict) -> dict:
    return {
        "origem_id": n["id"],
        "contrato_origem_id": n["cost_center_id"],
        "numero": n.get("number") or "",
        "cliente_nome": n.get("client_name") or "",
        "emitida_em": _data(n.get("issued_at")),
        "tipo": n.get("kind") or "principal",
        "valor": _dec(n.get("value")) or Decimal("0"),
        "observacoes": n.get("observations"),
        "origem_atualizado_em": _instante(n.get("updated_at")),
    }


def _linha_recebimento(r: dict) -> dict:
    return {
        "origem_id": r["id"],
        "nf_origem_id": r["invoice_id"],
        "data_pagamento": _data(r.get("payment_date")),
        "valor": _dec(r.get("value")) or Decimal("0"),
        "origem_atualizado_em": _instante(r.get("updated_at")),
    }


def _incremental(session, cliente, recurso: str, modelo, conversor, completo: bool) -> int:
    registro = marca(session, FONTE, recurso)
    desde = (
        None if completo or registro.marca_dados is None else registro.marca_dados - SOBREPOSICAO
    )
    vistos, nova_marca = set(), registro.marca_dados
    for pagina, watermark in cliente.paginar(
        recurso, recurso, updated_since=desde.isoformat() if desde else None
    ):
        upsert(session, modelo, [conversor(x) for x in pagina])
        vistos |= {x["id"] for x in pagina}
        if watermark:
            nova_marca = max(filter(None, [nova_marca, _instante(watermark)]))
    if completo:
        apagar_ausentes(session, modelo, vistos)
        registro.ultima_completa_em = func.now()
    registro.marca_dados = nova_marca
    return len(vistos)


def _exclusoes(session, cliente) -> int:
    registro = marca(session, FONTE, "deletions")
    total, nova = 0, registro.marca_exclusoes
    for pagina, watermark in cliente.paginar(
        "deletions",
        "deletions",
        types="Invoice,Receipt",
        since=registro.marca_exclusoes.isoformat() if registro.marca_exclusoes else None,
    ):
        nfs = [d["item_id"] for d in pagina if d["item_type"] == "Invoice"]
        recebimentos = [d["item_id"] for d in pagina if d["item_type"] == "Receipt"]
        total += apagar(session, RcNf, nfs) + apagar(session, RcRecebimento, recebimentos)
        if watermark:
            nova = max(filter(None, [nova, _instante(watermark)]))
    registro.marca_exclusoes = nova
    return total


def sincronizar(session, cliente, completo: bool = False) -> dict:
    contagens = {
        "clientes": _clientes(session, cliente),
        "contratos": _contratos(session, cliente),
        "aditivos": _ajustes(session, cliente),
        "previsoes": _previsoes(session, cliente),
        "nfs": _incremental(session, cliente, "invoices", RcNf, _linha_nf, completo),
        "recebimentos": _incremental(
            session, cliente, "receipts", RcRecebimento, _linha_recebimento, completo
        ),
        "exclusoes": _exclusoes(session, cliente),
    }
    session.flush()

    # Conferência: se a contagem divergir, a próxima volta pelo caminho completo.
    status = cliente.get("status")
    divergiu = []
    for recurso, modelo, chave in (
        ("invoices", RcNf, "invoices"),
        ("receipts", RcRecebimento, "receipts"),
    ):
        local = session.scalar(select(func.count()).select_from(modelo))
        if local != status.get(chave, {}).get("count"):
            divergiu.append(recurso)
    if divergiu and not completo:
        for recurso, modelo, conversor in (
            ("invoices", RcNf, _linha_nf),
            ("receipts", RcRecebimento, _linha_recebimento),
        ):
            if recurso in divergiu:
                _incremental(session, cliente, recurso, modelo, conversor, completo=True)
        contagens["reconciliado"] = divergiu
    salvar_marca(session)
    return contagens
