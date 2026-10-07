"""Espelho do Controle de Despesa.

Só entram as despesas dos centros que têm contrato na Receita (mesmo CR): a
Receita define quais contratos existem aqui. Contrato novo na Receita traz o
histórico inteiro do centro; contrato que some leva as despesas junto.

Centros, fornecedores e naturezas vêm inteiros. Despesas são incrementais; as
exclusões vêm da trigger do Controle, e a conferência por /status + /ids pega o
que escapar (restauração de backup lá, por exemplo).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.analise.normalizar import cr_norm, nome_norm
from app.models import CdCentro, CdDespesa, CdFornecedor, CdNatureza, RcContrato
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


def centros_com_contrato(session) -> list[int]:
    """Centros do Controle cujo CR tem contrato na Receita (ativo ou desativado)."""
    crs = select(RcContrato.cr_norm)
    return sorted(session.scalars(select(CdCentro.origem_id).where(CdCentro.cr_norm.in_(crs))))


def _filtro(centros) -> str:
    return ",".join(str(c) for c in sorted(centros))


def _baixar(session, cliente, centros: set[int], desde) -> tuple[set[int], datetime | None]:
    vistos, nova = set(), None
    for pagina, watermark in cliente.paginar(
        "despesas",
        "despesas",
        limite=2000,
        centro_ids=_filtro(centros),
        updated_since=desde.isoformat() if desde else None,
    ):
        # Filtra de novo aqui: um Controle sem o centro_ids devolveria tudo.
        linhas = [_linha(d) for d in pagina if d["centro_custo_id"] in centros]
        upsert(session, CdDespesa, linhas)
        vistos |= {linha["origem_id"] for linha in linhas}
        if watermark:
            nova = max(filter(None, [nova, _instante(watermark)]))
    return vistos, nova


def _despesas(session, cliente, completo: bool, centros: list[int]) -> int:
    registro = marca(session, FONTE, "despesas")
    permitidos = set(centros)

    # Contrato que saiu da Receita: as despesas do centro saem daqui.
    session.execute(delete(CdDespesa).where(CdDespesa.centro_origem_id.not_in(permitidos)))
    if not permitidos:
        return 0

    vistos, nova = set(), registro.marca_dados
    # Contrato novo na Receita: o histórico do centro vem inteiro, a marca não serve.
    ja_tem = set(session.scalars(select(CdDespesa.centro_origem_id).distinct()))
    novos = permitidos - ja_tem
    if novos and not completo:
        achados, marca_nova = _baixar(session, cliente, novos, None)
        vistos |= achados
        nova = max(filter(None, [nova, marca_nova]), default=None)

    desde = (
        None if completo or registro.marca_dados is None else registro.marca_dados - SOBREPOSICAO
    )
    achados, marca_nova = _baixar(session, cliente, permitidos, desde)
    vistos |= achados
    nova = max(filter(None, [nova, marca_nova]), default=None)

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
    centros = centros_com_contrato(session)
    contagens["centros_com_contrato"] = len(centros)
    contagens["despesas"] = _despesas(session, cliente, completo, centros)
    contagens["exclusoes"] = _exclusoes(session, cliente)
    session.flush()
    if not centros:
        return contagens

    filtro = _filtro(centros)
    status = cliente.get("status", centro_ids=filtro)["despesas"]
    esperado = status["count"]
    if _contagem(session) != esperado:
        ids = set(cliente.get("despesas/ids", centro_ids=filtro)["ids"])
        contagens["reconciliado"] = apagar_ausentes(session, CdDespesa, ids)
        session.flush()
        if _contagem(session) != esperado:
            contagens["despesas"] = _despesas(session, cliente, True, centros)
            session.flush()

    # A quantidade não vê um valor alterado que escapou; a soma vê.
    soma = status.get("sum_valor_baixado")
    if soma is not None and _soma(session) != Decimal(str(soma)):
        contagens["despesas"] = _despesas(session, cliente, True, centros)
        contagens["reconciliado_soma"] = True
    return contagens


def _contagem(session) -> int:
    return session.scalar(select(func.count()).select_from(CdDespesa))


def _soma(session) -> Decimal:
    return Decimal(str(session.scalar(select(func.coalesce(func.sum(CdDespesa.valor_baixado), 0)))))
