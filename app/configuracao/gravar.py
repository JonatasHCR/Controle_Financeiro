"""Gravação dos complementos. Telas e importação usam as mesmas funções.

Cada grupo é substituído por inteiro dentro do CR: o que veio é o novo estado.
As contagens (novas/alteradas/removidas) alimentam a prévia e a auditoria.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select

from app.models import CfgBm, CfgContrato, CfgItem, CfgPendencia, CfgPleito, DeparaItem, Parametros


@dataclass
class Contagem:
    novas: int = 0
    alteradas: int = 0
    removidas: int = 0
    avisos: list[str] = field(default_factory=list)

    def somar(self, outra: Contagem) -> Contagem:
        return Contagem(
            self.novas + outra.novas,
            self.alteradas + outra.alteradas,
            self.removidas + outra.removidas,
            self.avisos + outra.avisos,
        )

    @property
    def mudou(self) -> bool:
        return bool(self.novas or self.alteradas or self.removidas)

    def como_dict(self) -> dict:
        return {"novas": self.novas, "alteradas": self.alteradas, "removidas": self.removidas}


def _norm(v):
    if isinstance(v, Decimal):
        return v.normalize()
    if isinstance(v, str):
        return v.strip()
    return v


def _diff_por_chave(antes: dict, depois: dict) -> Contagem:
    """Linhas identificadas por chave (código do item, NF, natureza)."""
    c = Contagem()
    for chave, valor in depois.items():
        if chave not in antes:
            c.novas += 1
        elif antes[chave] != valor:
            c.alteradas += 1
    c.removidas = sum(1 for chave in antes if chave not in depois)
    return c


def _diff_sem_chave(antes: list[tuple], depois: list[tuple]) -> Contagem:
    """Pendências e pleitos não têm código: compara o conteúdo."""
    a, d = Counter(antes), Counter(depois)
    sobrou_antes = sum((a - d).values())
    sobrou_depois = sum((d - a).values())
    alteradas = min(sobrou_antes, sobrou_depois)
    return Contagem(
        novas=sobrou_depois - alteradas, alteradas=alteradas, removidas=sobrou_antes - alteradas
    )


# --- prazos e parâmetros ---------------------------------------------------------


def salvar_prazos(
    session, cr: str, fim_execucao: date | None, usuario_id: int | None, simular: bool = False
) -> Contagem:
    atual = session.get(CfgContrato, cr)
    antes = atual.fim_execucao if atual else None
    if antes == fim_execucao:
        return Contagem()
    if not simular:
        if atual is None:
            session.add(
                CfgContrato(cr_norm=cr, fim_execucao=fim_execucao, atualizado_por_id=usuario_id)
            )
        else:
            atual.fim_execucao, atual.atualizado_por_id = fim_execucao, usuario_id
    return Contagem(novas=0 if atual else 1, alteradas=1 if atual else 0)


def salvar_parametros(
    session,
    cr: str,
    tributos: Decimal | None,
    taxa: Decimal | None,
    usuario_id: int | None,
    simular: bool = False,
) -> Contagem:
    """Sem valores = volta ao padrão global."""
    atual = session.get(Parametros, cr)
    if tributos is None and taxa is None:
        if atual is None:
            return Contagem()
        if not simular:
            session.delete(atual)
        return Contagem(removidas=1)
    for nome, valor in (("tributos", tributos), ("taxa adm.", taxa)):
        if valor is None or not (Decimal("0") <= valor < Decimal("1")):
            raise ValueError(f"{nome}: informe um percentual entre 0 e 99,99")
    if atual and (_norm(atual.tributos), _norm(atual.taxa_adm)) == (_norm(tributos), _norm(taxa)):
        return Contagem()
    if not simular:
        if atual is None:
            session.add(
                Parametros(
                    cr_norm=cr, tributos=tributos, taxa_adm=taxa, atualizado_por_id=usuario_id
                )
            )
        else:
            atual.tributos, atual.taxa_adm, atual.atualizado_por_id = tributos, taxa, usuario_id
    return Contagem(novas=0 if atual else 1, alteradas=1 if atual else 0)


# --- itens -----------------------------------------------------------------------

CAMPOS_ITEM = (
    "descricao",
    "unidade",
    "quantidade",
    "custo_alvo",
    "custo_alvo_projetado",
    "quantidade_medida",
)


def substituir_itens(
    session, cr: str, linhas: list[dict], usuario_id: int | None, simular: bool = False
) -> Contagem:
    """linhas: codigo, descricao, unidade, quantidade, custo_alvo, custo_alvo_projetado e
    quantidade_medida."""
    codigos = [linha["codigo"] for linha in linhas]
    repetidos = {c for c in codigos if codigos.count(c) > 1}
    if repetidos:
        raise ValueError(f"código de item repetido: {', '.join(sorted(repetidos))}")
    existentes = {
        i.codigo: i for i in session.scalars(select(CfgItem).where(CfgItem.cr_norm == cr))
    }
    antes = {k: tuple(_norm(getattr(i, c)) for c in CAMPOS_ITEM) for k, i in existentes.items()}
    depois = {linha["codigo"]: tuple(_norm(linha.get(c)) for c in CAMPOS_ITEM) for linha in linhas}
    contagem = _diff_por_chave(antes, depois)
    if simular:
        return contagem
    for ordem, linha in enumerate(linhas):
        item = existentes.get(linha["codigo"])
        if item is None:
            item = CfgItem(cr_norm=cr, codigo=linha["codigo"])
            session.add(item)
        for campo in CAMPOS_ITEM:
            setattr(
                item,
                campo,
                linha.get(campo) if campo != "custo_alvo" else (linha.get(campo) or Decimal("0")),
            )
        item.unidade = linha.get("unidade") or ""
        item.ordem = ordem
        item.atualizado_por_id = usuario_id
    for codigo, item in existentes.items():
        if codigo not in depois:
            session.delete(item)
    return contagem


# --- de-para ---------------------------------------------------------------------


def salvar_depara(
    session, cr: str, mapa: dict[str, str], usuario_id: int | None, simular: bool = False
) -> Contagem:
    """mapa: natureza (nome_norm) → código do item ('' = não classificado de propósito)."""
    existentes = {
        d.natureza_nome_norm: d
        for d in session.scalars(select(DeparaItem).where(DeparaItem.cr_norm == cr))
    }
    contagem = _diff_por_chave({k: d.item_codigo for k, d in existentes.items()}, mapa)
    contagem.removidas = 0  # natureza fora do mapa continua como estava
    if simular:
        return contagem
    for natureza, item in mapa.items():
        atual = existentes.get(natureza)
        if atual is None:
            session.add(
                DeparaItem(
                    cr_norm=cr,
                    natureza_nome_norm=natureza,
                    item_codigo=item,
                    atualizado_por_id=usuario_id,
                )
            )
        elif atual.item_codigo != item:
            atual.item_codigo, atual.atualizado_por_id = item, usuario_id
    return contagem


# --- BMs -------------------------------------------------------------------------


def salvar_bms(
    session, cr: str, linhas: list[dict], usuario_id: int | None, simular: bool = False
) -> Contagem:
    """linhas: nf_origem_id, numero (None = sem BM), data_base."""
    existentes = {
        b.nf_origem_id: b for b in session.scalars(select(CfgBm).where(CfgBm.cr_norm == cr))
    }
    antes = {k: (b.numero, b.data_base) for k, b in existentes.items()}
    depois = {
        linha["nf_origem_id"]: (linha["numero"], linha.get("data_base"))
        for linha in linhas
        if linha.get("numero") is not None
    }
    contagem = _diff_por_chave(antes, depois)
    # NF que não veio na lista fica como está; só sai quando vier sem número
    removidas = [
        linha["nf_origem_id"]
        for linha in linhas
        if linha.get("numero") is None and linha["nf_origem_id"] in existentes
    ]
    contagem.removidas = len(removidas)
    if simular:
        return contagem
    for nf, (numero, data_base) in depois.items():
        atual = existentes.get(nf)
        if atual is None:
            session.add(
                CfgBm(
                    cr_norm=cr,
                    nf_origem_id=nf,
                    numero=numero,
                    data_base=data_base,
                    atualizado_por_id=usuario_id,
                )
            )
        else:
            atual.numero, atual.data_base, atual.atualizado_por_id = numero, data_base, usuario_id
    if removidas:
        session.execute(delete(CfgBm).where(CfgBm.nf_origem_id.in_(removidas)))
    return contagem


# --- pendências e pleitos -----------------------------------------------------------

CAMPOS_PENDENCIA = ("assunto", "prazo", "prioridade", "status")
CAMPOS_PLEITO = ("data_base", "descricao", "tipo", "status", "valor", "observacao")


def _substituir_lista(session, modelo, campos, cr, linhas, usuario_id, simular) -> Contagem:
    existentes = session.scalars(select(modelo).where(modelo.cr_norm == cr)).all()
    antes = [tuple(_norm(getattr(x, c)) for c in campos) for x in existentes]
    depois = [tuple(_norm(linha.get(c)) for c in campos) for linha in linhas]
    contagem = _diff_sem_chave(antes, depois)
    if simular or not contagem.mudou:
        return contagem
    session.execute(delete(modelo).where(modelo.cr_norm == cr))
    for linha in linhas:
        session.add(
            modelo(cr_norm=cr, atualizado_por_id=usuario_id, **{c: linha.get(c) for c in campos})
        )
    return contagem


def substituir_pendencias(session, cr, linhas, usuario_id, simular=False) -> Contagem:
    return _substituir_lista(
        session, CfgPendencia, CAMPOS_PENDENCIA, cr, linhas, usuario_id, simular
    )


def substituir_pleitos(session, cr, linhas, usuario_id, simular=False) -> Contagem:
    for linha in linhas:
        linha["valor"] = linha.get("valor") or Decimal("0")
    return _substituir_lista(session, CfgPleito, CAMPOS_PLEITO, cr, linhas, usuario_id, simular)
