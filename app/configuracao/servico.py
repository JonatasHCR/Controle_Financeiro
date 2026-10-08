"""Regras da configuração (complementos por CR)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from sqlalchemy import func, select

from app.analise.dados import Contrato, carregar_contratos
from app.analise.normalizar import nome_norm
from app.models import (
    CdCentro,
    CdDespesa,
    CdNatureza,
    CfgBm,
    CfgItem,
    CfgNaturezaCredito,
    CfgPendencia,
    CfgPleito,
    DeparaItem,
    RcContrato,
    RcNf,
)


class ErroDeValidacao(ValueError):
    pass


# --- conversões dos campos de formulário e planilha ---------------------------


def decimal_br(valor, campo: str, obrigatorio: bool = False) -> Decimal | None:
    """Aceita 1.234,56 e 1234.56."""
    if valor is None or str(valor).strip() == "":
        if obrigatorio:
            raise ErroDeValidacao(f"{campo}: obrigatório")
        return None
    if isinstance(valor, int | float | Decimal):
        return Decimal(str(valor))
    texto = str(valor).strip().replace("R$", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation as erro:
        raise ErroDeValidacao(f"{campo}: '{valor}' não é um número") from erro


def data_br(valor, campo: str) -> date | None:
    """Aceita aaaa-mm-dd, dd/mm/aaaa e data/datetime da planilha."""
    if valor is None or str(valor).strip() == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    try:
        if "/" in texto:
            dia, mes, ano = texto.split("/")
            return date(int(ano), int(mes), int(dia))
        return date.fromisoformat(texto[:10])
    except ValueError as erro:
        raise ErroDeValidacao(f"{campo}: '{valor}' não é uma data") from erro


def mes_br(valor, campo: str) -> date | None:
    """Data-base: aaaa-mm, mm/aaaa ou qualquer data do mês → primeiro dia."""
    if valor is None or str(valor).strip() == "":
        return None
    if isinstance(valor, date):
        return date(valor.year, valor.month, 1)
    texto = str(valor).strip()
    try:
        if "/" in texto:
            mes, ano = texto.split("/")[-2:]
            return date(int(ano), int(mes), 1)
        ano, mes = texto.split("-")[:2]
        return date(int(ano), int(mes), 1)
    except ValueError as erro:
        raise ErroDeValidacao(f"{campo}: '{valor}' não é um mês (use mm/aaaa)") from erro


def opcao(valor, campo: str, opcoes: tuple[str, ...], padrao: str) -> str:
    if valor is None or str(valor).strip() == "":
        return padrao
    alvo = nome_norm(valor)
    for item in opcoes:
        if nome_norm(item) == alvo:
            return item
    raise ErroDeValidacao(f"{campo}: use {', '.join(opcoes)}")


def linhas_do_form(form, prefixo: str) -> list[dict]:
    """Campos `prefixo-<n>-<campo>` viram uma lista de dicionários, na ordem de n."""
    grupos = defaultdict(dict)
    for chave, valor in form.items():
        partes = chave.split("-", 2)
        if len(partes) == 3 and partes[0] == prefixo and partes[1].isdigit():
            grupos[int(partes[1])][partes[2]] = valor
    return [grupos[i] for i in sorted(grupos)]


# --- leitura para as telas ------------------------------------------------------


def contrato_por_cr(session, cr: str) -> Contrato | None:
    return next((c for c in carregar_contratos(session) if c.cr == cr), None)


def naturezas_do_cr(session, cr: str) -> list[dict]:
    """Naturezas com despesa neste CR, com o total e o item do de-para."""
    linhas = session.execute(
        select(
            CdNatureza.nome,
            CdNatureza.nome_norm,
            func.sum(func.coalesce(CdDespesa.valor_baixado, 0)),
        )
        .join(CdNatureza, CdNatureza.origem_id == CdDespesa.natureza_origem_id)
        .join(CdCentro, CdCentro.origem_id == CdDespesa.centro_origem_id)
        .where(CdCentro.cr_norm == cr)
        .group_by(CdNatureza.nome, CdNatureza.nome_norm)
        .order_by(func.sum(func.coalesce(CdDespesa.valor_baixado, 0)).desc())
    ).all()
    mapa = {
        d.natureza_nome_norm: d.item_codigo
        for d in session.scalars(select(DeparaItem).where(DeparaItem.cr_norm == cr))
    }
    itens = session.scalars(select(CfgItem).where(CfgItem.cr_norm == cr)).all()
    com_credito = set(session.scalars(select(CfgNaturezaCredito.natureza_nome_norm)))
    resultado = []
    for nome, norm, total in linhas:
        definido = norm in mapa
        resultado.append(
            {
                "nome": nome,
                "norm": norm,
                "total": float(total or 0),
                "item": mapa.get(norm, ""),
                "definido": definido,
                "credito": norm in com_credito,
                "sugestao": "" if definido else sugerir_item(nome, itens),
            }
        )
    return resultado


def sugerir_item(natureza: str, itens: list[CfgItem]) -> str:
    """Item de descrição mais parecida com a natureza (só sugere acima de 45%)."""
    alvo = nome_norm(natureza)
    melhor, nota = "", 0.0
    for it in itens:
        valor = SequenceMatcher(None, alvo, nome_norm(it.descricao)).ratio()
        if valor > nota:
            melhor, nota = it.codigo, valor
    return melhor if nota >= 0.45 else ""


def nfs_do_cr(session, cr: str) -> list[dict]:
    origem = session.scalar(select(RcContrato.origem_id).where(RcContrato.cr_norm == cr))
    if origem is None:
        return []
    bms = {b.nf_origem_id: b for b in session.scalars(select(CfgBm).where(CfgBm.cr_norm == cr))}
    nfs = session.scalars(
        select(RcNf)
        .where(RcNf.contrato_origem_id == origem)
        .order_by(RcNf.emitida_em.desc(), RcNf.numero.desc())
    ).all()
    return [
        {
            "id": n.origem_id,
            "numero": n.numero,
            "emitida_em": n.emitida_em,
            "tipo": n.tipo,
            "valor": float(n.valor),
            "bm": bms[n.origem_id].numero if n.origem_id in bms else None,
            "data_base": bms[n.origem_id].data_base if n.origem_id in bms else None,
        }
        for n in nfs
    ]


def status_dos_crs(session) -> list[dict]:
    """O que falta completar em cada CR, para a lista da Configuração."""
    contratos = carregar_contratos(session)
    soma_itens = dict(
        session.execute(
            select(CfgItem.cr_norm, func.sum(CfgItem.custo_alvo)).group_by(CfgItem.cr_norm)
        ).all()
    )
    qtd_itens = dict(
        session.execute(select(CfgItem.cr_norm, func.count()).group_by(CfgItem.cr_norm)).all()
    )
    pendencias = dict(
        session.execute(
            select(CfgPendencia.cr_norm, func.count())
            .where(CfgPendencia.status == "ABERTA")
            .group_by(CfgPendencia.cr_norm)
        ).all()
    )
    pleitos = dict(
        session.execute(select(CfgPleito.cr_norm, func.count()).group_by(CfgPleito.cr_norm)).all()
    )
    sem_bm = dict(
        session.execute(
            select(RcContrato.cr_norm, func.count())
            .join(RcNf, RcNf.contrato_origem_id == RcContrato.origem_id)
            .outerjoin(CfgBm, CfgBm.nf_origem_id == RcNf.origem_id)
            .where(CfgBm.id.is_(None))
            .group_by(RcContrato.cr_norm)
        ).all()
    )
    cobertura = _cobertura_depara(session)

    lista = []
    for c in contratos:
        alvo_contratual = c.valor * (1 - c.tributos) / (1 + c.taxa_adm) if c.valor else 0
        soma = float(soma_itens.get(c.cr) or 0)
        lista.append(
            {
                "contrato": c,
                "itens": qtd_itens.get(c.cr, 0),
                "itens_ok": bool(alvo_contratual)
                and abs(soma - alvo_contratual) / alvo_contratual < 0.01,
                "cobertura": cobertura.get(c.cr),
                "sem_bm": sem_bm.get(c.cr, 0),
                "pendencias": pendencias.get(c.cr, 0),
                "pleitos": pleitos.get(c.cr, 0),
            }
        )
    return lista


def _cobertura_depara(session) -> dict[str, float]:
    """Fração do custo de cada CR que já está ligada a um item."""
    mapeadas = {
        (d.cr_norm, d.natureza_nome_norm)
        for d in session.scalars(select(DeparaItem).where(DeparaItem.item_codigo != ""))
    }
    totais = defaultdict(float)
    classificados = defaultdict(float)
    for cr, natureza, total in session.execute(
        select(
            CdCentro.cr_norm,
            CdNatureza.nome_norm,
            func.sum(func.coalesce(CdDespesa.valor_baixado, 0)),
        )
        .join(CdCentro, CdCentro.origem_id == CdDespesa.centro_origem_id)
        .join(CdNatureza, CdNatureza.origem_id == CdDespesa.natureza_origem_id)
        .group_by(CdCentro.cr_norm, CdNatureza.nome_norm)
    ).all():
        totais[cr] += float(total or 0)
        if (cr, natureza) in mapeadas:
            classificados[cr] += float(total or 0)
    return {cr: (classificados[cr] / t if t else 1.0) for cr, t in totais.items()}


def alvo_contratual(c: Contrato) -> float:
    return c.valor * (1 - c.tributos) / (1 + c.taxa_adm) if c.valor else 0.0


# --- parâmetros em lote ------------------------------------------------------------

ALVOS = ("todos", "cr", "cli", "coord")


def contratos_do_alvo(contratos: list[Contrato], alvo: str, selecao: list[str]) -> list[Contrato]:
    """Contratos que batem com a seleção: centros de custo, clientes ou coordenadores."""
    if alvo == "todos":
        return list(contratos)
    escolhidos = set(selecao)
    if alvo == "cr":
        return [c for c in contratos if c.cr in escolhidos]
    if alvo == "cli":
        return [c for c in contratos if c.cliente in escolhidos]
    alvo_norm = {nome_norm(n) for n in escolhidos}
    return [c for c in contratos if alvo_norm & {nome_norm(n) for n in c.coordenadores}]
