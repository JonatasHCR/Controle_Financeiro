"""Leitura do banco para o painel: os contratos da Receita e os lançamentos
dos CRs escolhidos, já agregados no SQL."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from flask import current_app
from sqlalchemy import func, select

from app.analise.normalizar import nome_norm
from app.analise.periodo import ym
from app.models import (
    CdCentro,
    CdDespesa,
    CdNatureza,
    CfgBm,
    CfgContrato,
    CfgItem,
    CfgNaturezaCredito,
    CfgPendencia,
    CfgPleito,
    DeparaItem,
    Parametros,
    RcAjuste,
    RcCliente,
    RcContrato,
    RcContratoCoordenador,
    RcNf,
    RcRecebimento,
)

NAO_CLASSIFICADO = "NC"
# Natureza sem ligação vira item com o próprio nome: "nat:LOCAÇÃO DE VEÍCULOS".
PREFIXO_NATUREZA = "nat:"


@dataclass
class Contrato:
    cr: str
    nome: str
    descricao: str
    numero: str | None = None
    cliente: str = "Sem cadastro na Receita"
    coordenadores: list[str] = field(default_factory=list)
    receita: bool = True
    despesa: bool = True
    ativo: bool = True
    origem_id: int | None = None
    valor: float = 0.0
    valor_inicial: float = 0.0
    inicio: date | None = None
    fim_vigencia: date | None = None
    fim_execucao: date | None = None
    tributos: float = 0.20
    taxa_adm: float = 0.15
    cor: int = 0

    @property
    def horizonte(self) -> date | None:
        datas = [d for d in (self.fim_vigencia, self.fim_execucao) if d]
        return min(datas) if datas else None

    @property
    def aditivos(self) -> float:
        return self.valor - self.valor_inicial

    @property
    def status(self) -> str:
        if not self.receita:
            return "—"
        fim = self.fim_execucao or self.fim_vigencia
        return "CONCLUÍDO" if fim and fim < date.today() else "EM EXECUÇÃO"

    @property
    def bdi(self) -> float:
        return (1 + self.taxa_adm) / (1 - self.tributos)


def _f(valor) -> float:
    return float(valor) if isinstance(valor, Decimal | int | float) else 0.0


def _parametros(session) -> dict[str, tuple[float, float]]:
    cfg = current_app.config
    padrao = (float(cfg.get("TRIBUTOS_PADRAO", 0.20)), float(cfg.get("TAXA_ADM_PADRAO", 0.15)))
    linhas = {
        p.cr_norm: (float(p.tributos), float(p.taxa_adm))
        for p in session.scalars(select(Parametros))
    }
    linhas.setdefault("*", padrao)
    return linhas


def carregar_contratos(session) -> list[Contrato]:
    """Os contratos da Receita. CR que só existe no Controle não entra."""
    clientes = {c.origem_id: c.nome for c in session.scalars(select(RcCliente))}
    coords = defaultdict(list)
    for linha in session.scalars(select(RcContratoCoordenador).order_by(RcContratoCoordenador.id)):
        coords[linha.contrato_origem_id].append(linha.nome)
    cfg = {c.cr_norm: c for c in session.scalars(select(CfgContrato))}
    params = _parametros(session)
    centros = {c.cr_norm: c for c in session.scalars(select(CdCentro))}

    # valor inicial = antes do primeiro aditivo de valor
    iniciais = {}
    for aj in session.scalars(
        select(RcAjuste)
        .where(RcAjuste.tipo == "valor")
        .order_by(RcAjuste.criado_origem_em, RcAjuste.origem_id)
    ):
        iniciais.setdefault(aj.contrato_origem_id, aj.valor_anterior)

    contratos = []
    vistos = set()
    for rc in session.scalars(select(RcContrato)):
        if rc.cr_norm in vistos:
            continue
        vistos.add(rc.cr_norm)
        trib, taxa = params.get(rc.cr_norm, params["*"])
        valor = _f(rc.valor)
        contratos.append(
            Contrato(
                cr=rc.cr_norm,
                nome=rc.descricao or rc.cr_code,
                descricao=rc.descricao or rc.cr_code,
                numero=rc.numero_contrato,
                cliente=clientes.get(rc.cliente_origem_id, "—"),
                coordenadores=coords.get(rc.origem_id, []),
                receita=True,
                despesa=rc.cr_norm in centros,
                ativo=rc.ativo,
                origem_id=rc.origem_id,
                valor=valor,
                valor_inicial=_f(iniciais.get(rc.origem_id, rc.valor)),
                inicio=rc.data_inicio,
                fim_vigencia=rc.data_fim,
                fim_execucao=(cfg[rc.cr_norm].fim_execucao if rc.cr_norm in cfg else None)
                or rc.data_fim,
                tributos=trib,
                taxa_adm=taxa,
            )
        )
    contratos.sort(key=lambda c: (len(c.cr), c.cr))
    for i, c in enumerate(contratos):
        c.cor = i % 8
    return contratos


def limites_de_data(session) -> tuple[date | None, date | None]:
    nf_min, nf_max = session.execute(
        select(func.min(RcNf.emitida_em), func.max(RcNf.emitida_em))
    ).one()
    d_min, d_max = session.execute(
        select(func.min(CdDespesa.data_baixa), func.max(CdDespesa.data_baixa))
    ).one()
    minimos = [d for d in (nf_min, d_min) if d]
    maximos = [d for d in (nf_max, d_max) if d]
    return (min(minimos) if minimos else None, max(maximos) if maximos else None)


def base_maxima(session, hoje: date | None = None) -> str:
    """Mês mais recente com dado (data-base de NF ou baixa de despesa), sem passar de hoje."""
    hoje = hoje or date.today()
    candidatos = [
        session.scalar(select(func.max(CfgBm.data_base))),
        session.scalar(select(func.max(RcNf.emitida_em))),
        session.scalar(select(func.max(CdDespesa.data_baixa))),
    ]
    meses = [ym(d) for d in candidatos if d]
    return min(max(meses), ym(hoje)) if meses else ym(hoje)


@dataclass
class Lancamentos:
    nfs: list[dict]
    custos: list[tuple[str, date, str, float]]  # (cr, data_baixa, item, valor)
    # Parte dos custos de natureza que gera crédito de PIS/COFINS: (cr, data_baixa, valor)
    creditos: list[tuple[str, date, float]]
    itens: dict[str, list[CfgItem]]
    pendencias: list[CfgPendencia]
    pleitos: list[CfgPleito]


def carregar_lancamentos(session, contratos: list[Contrato]) -> Lancamentos:
    crs = [c.cr for c in contratos]
    por_origem = {c.origem_id: c.cr for c in contratos if c.origem_id}

    nfs = []
    if por_origem:
        recebido = dict(
            session.execute(
                select(RcRecebimento.nf_origem_id, func.sum(RcRecebimento.valor)).group_by(
                    RcRecebimento.nf_origem_id
                )
            ).all()
        )
        bms = {
            b.nf_origem_id: b for b in session.scalars(select(CfgBm).where(CfgBm.cr_norm.in_(crs)))
        }
        consulta = select(RcNf).where(RcNf.contrato_origem_id.in_(list(por_origem)))
        for nf in session.scalars(consulta):
            bm = bms.get(nf.origem_id)
            valor = _f(nf.valor)
            pago = _f(recebido.get(nf.origem_id, 0))
            nfs.append(
                {
                    "id": nf.origem_id,
                    "cr": por_origem[nf.contrato_origem_id],
                    "numero": nf.numero,
                    "emitida_em": nf.emitida_em,
                    "competencia": ym(bm.data_base) if bm and bm.data_base else ym(nf.emitida_em),
                    "bm": bm.numero if bm else None,
                    "tipo": nf.tipo,
                    "valor": valor,
                    "recebido": pago,
                    "paga": pago >= valor - 0.005,
                }
            )

    depara = defaultdict(dict)
    for d in session.scalars(select(DeparaItem).where(DeparaItem.cr_norm.in_(crs))):
        depara[d.cr_norm][d.natureza_nome_norm] = d.item_codigo

    com_credito = set(session.scalars(select(CfgNaturezaCredito.natureza_nome_norm)))
    custos, creditos = [], []
    linhas = session.execute(
        select(
            CdCentro.cr_norm,
            CdDespesa.data_baixa,
            CdNatureza.nome_norm,
            func.min(CdNatureza.nome),
            func.sum(func.coalesce(CdDespesa.valor_baixado, 0)),
        )
        .join(CdCentro, CdCentro.origem_id == CdDespesa.centro_origem_id)
        .join(CdNatureza, CdNatureza.origem_id == CdDespesa.natureza_origem_id)
        .where(CdCentro.cr_norm.in_(crs))
        .group_by(CdCentro.cr_norm, CdDespesa.data_baixa, CdNatureza.nome_norm)
    ).all()
    for cr, data_baixa, natureza, nome, valor in linhas:
        # Sem ligação na configuração, o item é a própria natureza.
        item = depara[cr].get(natureza) or PREFIXO_NATUREZA + nome
        custos.append((cr, data_baixa, item, _f(valor)))
        if natureza in com_credito:
            creditos.append((cr, data_baixa, _f(valor)))

    itens = defaultdict(list)
    for it in session.scalars(
        select(CfgItem).where(CfgItem.cr_norm.in_(crs)).order_by(CfgItem.ordem, CfgItem.id)
    ):
        itens[it.cr_norm].append(it)

    pendencias = session.scalars(
        select(CfgPendencia)
        .where(CfgPendencia.cr_norm.in_(crs), CfgPendencia.status == "ABERTA")
        .order_by(CfgPendencia.prazo.asc().nulls_last())
    ).all()
    pleitos = session.scalars(
        select(CfgPleito)
        .where(CfgPleito.cr_norm.in_(crs))
        .order_by(CfgPleito.data_base.desc().nulls_last())
    ).all()
    return Lancamentos(nfs, custos, creditos, itens, list(pendencias), list(pleitos))


def nomes_coordenadores(contratos: list[Contrato]) -> list[str]:
    vistos = {}
    for c in contratos:
        for nome in c.coordenadores:
            vistos.setdefault(nome_norm(nome), nome)
    return sorted(vistos.values(), key=nome_norm)
