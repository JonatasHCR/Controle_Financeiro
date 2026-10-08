"""Monta tudo o que a tela, a impressão e o PDF mostram.

Um objeto só (dict serializável), para que os três números batam sempre.
Líquida = bruta − tributos; resultado = líquida − custo realizado. No resumo
agrupado entram também PIS/COFINS (com crédito das naturezas marcadas) e a
taxa adm. de cada contrato sobre a bruta.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.analise.dados import (
    NAO_CLASSIFICADO,
    PREFIXO_NATUREZA,
    Contrato,
    base_maxima,
    carregar_contratos,
    carregar_lancamentos,
    limites_de_data,
    nomes_coordenadores,
)
from app.analise.normalizar import nome_norm
from app.analise.periodo import (
    Filtro,
    Periodo,
    add_meses,
    data_br,
    fim_do_mes,
    rotulo_mes,
    ym,
)
from app.models import PERFIS


def _passa(contrato: Contrato, filtro: Filtro) -> bool:
    if filtro.clientes and contrato.cliente not in filtro.clientes:
        return False
    if filtro.coordenadores:
        alvo = {nome_norm(n) for n in filtro.coordenadores}
        if not alvo & {nome_norm(n) for n in contrato.coordenadores}:
            return False
    return True


def visiveis_para(contratos: list[Contrato], usuario) -> list[Contrato]:
    """Leitor que é coordenador vê só os próprios CRs; os demais veem todos."""
    if usuario is None or usuario.nivel > PERFIS.index("leitor"):
        return contratos
    meu = nome_norm(usuario.nome)
    meus = [c for c in contratos if meu in {nome_norm(n) for n in c.coordenadores}]
    return meus or contratos


# chave do Filtro → (título da coluna, singular, plural)
AGRUPAR = {
    "cli": ("Contratante", "contratante", "contratantes"),
    "coord": ("Coordenador", "coordenador", "coordenadores"),
    "cr": ("Centro de custo", "centro de custo", "centros de custo"),
}


def rotulos(filtro: Filtro, selecionados: list[Contrato]) -> dict:
    """Filtro vazio = "Todos"; com seleção, só o que foi escolhido."""
    um = selecionados[0] if len(selecionados) == 1 else None
    if um:
        titulo = f"{um.cr} · {um.descricao}"
    elif filtro.crs:
        titulo = "Contratos " + ", ".join(filtro.crs)
    else:
        titulo = ""
    if filtro.coordenadores:
        gestor = ", ".join(filtro.coordenadores)
    elif um and um.coordenadores:
        gestor = " / ".join(um.coordenadores)
    else:
        gestor = "Todos"
    return {
        "cliente": ", ".join(filtro.clientes) or "Todos",
        "coordenador": ", ".join(filtro.coordenadores) or "Todos",
        "contratos": ", ".join(filtro.crs) if filtro.crs else f"Todos ({len(selecionados)})",
        "titulo": titulo,
        "gestor": gestor,
        "nf": "Só não pagas" if filtro.nf == "open" else "Todas",
        "agrupar": AGRUPAR[filtro.agrupar][0],
    }


def _tempo(c: Contrato, corte: str) -> float:
    if not c.inicio or not c.horizonte:
        return 0.0
    total = (c.horizonte - c.inicio).days
    if total <= 0:
        return 1.0
    base = min(fim_do_mes(corte), fim_do_mes(ym(c.horizonte)))
    return max(0.0, min(1.0, (base - c.inicio).days / total))


def nome_do_item(codigo: str) -> str:
    if codigo.startswith(PREFIXO_NATUREZA):
        return codigo[len(PREFIXO_NATUREZA) :]
    if codigo == NAO_CLASSIFICADO:
        return "Não classificado"
    return f"{codigo} (item não cadastrado)"


def _ritmo(gap: float) -> tuple[str, str]:
    if gap < -0.20:
        return "crit", "bem atrás do tempo"
    if gap < -0.05:
        return "warn", "atrás do tempo"
    if gap <= 0.05:
        return "ok", "em linha"
    return "info", "à frente do tempo"


def opcoes(contratos: list[Contrato], filtro: Filtro) -> dict:
    candidatos = [c for c in contratos if _passa(c, filtro)]
    return {
        "clientes": sorted({c.cliente for c in contratos}),
        "coordenadores": nomes_coordenadores(contratos),
        "contratos": [_resumo(c) for c in candidatos],
    }


def _resumo(c: Contrato) -> dict:
    return {
        "cr": c.cr,
        "nome": c.nome,
        "cliente": c.cliente,
        "coordenadores": c.coordenadores,
        "cor": c.cor,
        "receita": c.receita,
        "despesa": c.despesa,
        "ativo": c.ativo,
    }


def _ficha(c: Contrato) -> dict:
    return {
        **_resumo(c),
        "descricao": c.descricao,
        "numero": c.numero,
        "status": c.status,
        "inicio": c.inicio.isoformat() if c.inicio else None,
        "fim_execucao": c.fim_execucao.isoformat() if c.fim_execucao else None,
        "fim_vigencia": c.fim_vigencia.isoformat() if c.fim_vigencia else None,
        "horizonte": c.horizonte.isoformat() if c.horizonte else None,
        "valor": c.valor,
        "valor_inicial": c.valor_inicial,
        "aditivos": c.aditivos,
    }


def montar_painel(session, filtro: Filtro, usuario=None, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    todos = visiveis_para(carregar_contratos(session), usuario)
    candidatos = [c for c in todos if _passa(c, filtro)]
    escolhidos = set(filtro.crs)
    cs = [c for c in candidatos if not escolhidos or c.cr in escolhidos]

    data_min, data_max = limites_de_data(session)
    periodo = Periodo.resolver(filtro, base_maxima(session, hoje), data_min, data_max)
    corte = periodo.corte

    base = {
        "meta": {
            "periodo": periodo.texto,
            "modo": periodo.modo,
            "mes": periodo.mes,
            "de": periodo.de.isoformat() if periodo.de else None,
            "ate": periodo.ate.isoformat() if periodo.ate else None,
            "corte": corte,
            "corte_txt": rotulo_mes(corte),
            "base_max": periodo.base_max,
            "data_min": data_min.isoformat() if data_min else None,
            "data_max": data_max.isoformat() if data_max else None,
            "hoje": hoje.isoformat(),
            "rotulos": rotulos(filtro, cs),
            "meses_base": _meses_base(data_min, periodo.base_max),
            "estado": {"nf": filtro.nf, "agrupar": filtro.agrupar},
        },
        "opcoes": opcoes(todos, filtro),
        "contratos": [_ficha(c) for c in cs],
    }
    if not cs:
        return {**base, "vazio": True}

    lanc = carregar_lancamentos(session, cs)
    por_cr = {c.cr: c for c in cs}

    # --- receita e custo no período -------------------------------------------
    nfs_periodo = [n for n in lanc.nfs if periodo.nf_no_periodo(n["competencia"], n["emitida_em"])]
    fat_c = defaultdict(float)
    for n in nfs_periodo:
        fat_c[n["cr"]] += n["valor"]
    cus_c = defaultdict(float)
    for cr, data_baixa, _item, valor in lanc.custos:
        if periodo.despesa_no_periodo(data_baixa):
            cus_c[cr] += valor

    valor_total = sum(c.valor for c in cs)
    fat = sum(fat_c.values())
    cus = sum(cus_c.values())
    trib = sum(fat_c[c.cr] * c.tributos for c in cs)
    liq = fat - trib
    cascata = {
        "valor": valor_total,
        "fat": fat,
        "trib": trib,
        "liq": liq,
        "cus": cus,
        "res": liq - cus,
        "n_nfs": len(nfs_periodo),
        "tributos_txt": _pct_param({c.tributos for c in cs}),
        "mes": periodo.modo == "mes",
    }

    # --- recebimento -------------------------------------------------------------
    pago = sum(n["valor"] for n in nfs_periodo if n["paga"])
    aberto = sum(n["valor"] for n in nfs_periodo if not n["paga"])
    por_contrato = []
    abertas = []
    for c in cs:
        doc = [n for n in nfs_periodo if n["cr"] == c.cr]
        p = sum(n["valor"] for n in doc if n["paga"])
        a = sum(n["valor"] for n in doc if not n["paga"])
        if p + a:
            por_contrato.append({"cr": c.cr, "nome": c.nome, "cor": c.cor, "pago": p, "aberto": a})
        pend = sorted((n for n in doc if not n["paga"]), key=lambda n: n["emitida_em"])
        if pend:
            abertas.append(
                {
                    "cr": c.cr,
                    "nome": c.nome,
                    "cor": c.cor,
                    "total": sum(n["valor"] - n["recebido"] for n in pend),
                    "nfs": [
                        {
                            "bm": n["bm"],
                            "nf": n["numero"],
                            "valor": n["valor"] - n["recebido"],
                            "dias": (hoje - n["emitida_em"]).days,
                        }
                        for n in pend
                    ],
                }
            )
    recebimento = {
        "total": pago + aberto,
        "pago": pago,
        "aberto": aberto,
        "n": len(nfs_periodo),
        "n_pago": sum(1 for n in nfs_periodo if n["paga"]),
        "por_contrato": por_contrato,
        "abertas": abertas,
    }

    # --- série mensal ----------------------------------------------------------------
    inicio_geral = (
        min((ym(c.inicio) for c in cs if c.inicio), default=None)
        or _primeiro_mes_custo(lanc)
        or corte
    )
    if periodo.modo == "mes":
        m0 = add_meses(corte, -11)
    elif periodo.modo == "intervalo":
        m0 = max(ym(periodo.de), add_meses(corte, -35))
    else:
        m0 = max(inicio_geral, add_meses(corte, -23))
    meses = _intervalo_meses(m0, corte)
    liq_mes = defaultdict(float)
    for n in lanc.nfs:
        liq_mes[n["competencia"]] += n["valor"] * (1 - por_cr[n["cr"]].tributos)
    cus_mes = defaultdict(float)
    for _cr, data_baixa, _item, valor in lanc.custos:
        cus_mes[ym(data_baixa)] += valor
    mensal = {
        "meses": meses,
        "rotulos": [rotulo_mes(m) for m in meses],
        "rl": [liq_mes[m] for m in meses],
        "cu": [cus_mes[m] for m in meses],
        "g": [liq_mes[m] - cus_mes[m] for m in meses],
        "destaque": [periodo.mes_no_periodo(m) for m in meses],
    }

    # --- execução × tempo ------------------------------------------------------------
    fat_ate = defaultdict(float)
    for n in lanc.nfs:
        if n["competencia"] <= corte:
            fat_ate[n["cr"]] += n["valor"]
    execucao = []
    for c in cs:
        if not c.receita:
            continue
        fc = fat_ate[c.cr] / c.valor if c.valor else 0.0
        tp = _tempo(c, corte)
        classe, texto = _ritmo(fc - tp)
        execucao.append(
            {
                "cr": c.cr,
                "nome": c.nome,
                "cor": c.cor,
                "fat": fat_ate[c.cr],
                "valor": c.valor,
                "fc": fc,
                "tp": tp,
                "gap": fc - tp,
                "classe": classe,
                "texto": texto,
                "despesa": c.despesa,
            }
        )

    # --- custo por item ------------------------------------------------------------------
    real_periodo = defaultdict(float)
    for cr, data_baixa, item, valor in lanc.custos:
        if periodo.despesa_no_periodo(data_baixa):
            real_periodo[(cr, item)] += valor
    nomes_item = {(cr, it.codigo): it.descricao for cr, its in lanc.itens.items() for it in its}
    itens_periodo = sorted(
        (
            {
                "cr": cr,
                "d": nomes_item.get((cr, item), nome_do_item(item)),
                "v": v,
                "cor": por_cr[cr].cor,
            }
            for (cr, item), v in real_periodo.items()
            if v
        ),
        key=lambda x: -x["v"],
    )[:10]

    # --- pendências, pleitos, NFs --------------------------------------------------------
    pendencias = [
        {
            "cr": p.cr_norm,
            "cor": por_cr[p.cr_norm].cor,
            "assunto": p.assunto,
            "prazo": p.prazo.isoformat() if p.prazo else None,
            "dias": (p.prazo - hoje).days if p.prazo else None,
            "prioridade": p.prioridade,
        }
        for p in lanc.pendencias
    ]
    pleitos = [
        {
            "cr": p.cr_norm,
            "cor": por_cr[p.cr_norm].cor,
            "descricao": p.descricao,
            "tipo": p.tipo,
            "status": p.status,
            "valor": float(p.valor or 0),
            "data_base": rotulo_mes(ym(p.data_base)) if p.data_base else "—",
        }
        for p in lanc.pleitos
    ]
    potencial = sum(p["valor"] for p in pleitos)
    aprovado = sum(p["valor"] for p in pleitos if p["status"] in ("VALIDADO", "FEITO"))
    lista_nfs = sorted(
        (n for n in nfs_periodo if filtro.nf == "all" or not n["paga"]),
        key=lambda n: (n["competencia"], n["numero"]),
        reverse=True,
    )

    return {
        **base,
        "vazio": False,
        "ficha": {
            "fat": sum(fat_ate.values()),
            "valor": valor_total,
            "exec": sum(fat_ate.values()) / valor_total if valor_total else 0.0,
            "tempo": (
                _tempo(cs[0], corte)
                if len(cs) == 1
                else (
                    sum(_tempo(c, corte) * c.valor for c in cs) / valor_total
                    if valor_total
                    else 0.0
                )
            ),
            "tempo_txt": _tempo_txt(cs, corte),
            "data_base_txt": rotulo_mes(corte),
        },
        "cascata": cascata,
        "recebimento": recebimento,
        "mensal": mensal,
        "por_grupo": _por_grupo(cs, filtro.agrupar, fat_c, cus_c, _creditos(lanc, periodo)),
        "execucao": execucao,
        "sem_receita": [c.cr for c in cs if not c.receita],
        "itens": itens_periodo,
        "pendencias": pendencias,
        "pleitos": {"lista": pleitos, "potencial": potencial, "aprovado": aprovado},
        "nfs": {
            "lista": [
                {
                    "cr": n["cr"],
                    "cor": por_cr[n["cr"]].cor,
                    "bm": n["bm"],
                    "data_base": rotulo_mes(n["competencia"]),
                    "numero": n["numero"],
                    "emitida_em": data_br(n["emitida_em"]),
                    "tipo": n["tipo"],
                    "valor": n["valor"],
                    "paga": n["paga"],
                }
                for n in lista_nfs
            ],
            "so_abertas": filtro.nf == "open",
            "a_receber": aberto,
            "n_a_receber": sum(1 for n in nfs_periodo if not n["paga"]),
            "pago": pago,
            "n_pago": recebimento["n_pago"],
        },
    }


def _pct_param(valores: set[float], casas: int = 0) -> str:
    if len(valores) == 1:
        return f"{next(iter(valores)) * 100:.{casas}f}%".replace(".", ",")
    return "por contrato"


def _intervalo_meses(m0: str, m1: str) -> list[str]:
    meses, m = [], m0
    while m <= m1:
        meses.append(m)
        m = add_meses(m, 1)
    return meses


def _meses_base(data_min: date | None, base_max: str) -> list[str]:
    inicio = ym(data_min) if data_min else base_max
    return list(reversed(_intervalo_meses(inicio, base_max)))


def _primeiro_mes_custo(lanc) -> str | None:
    datas = [d for _cr, d, _i, _v in lanc.custos]
    return ym(min(datas)) if datas else None


def _tempo_txt(cs: list[Contrato], corte: str) -> str:
    if len(cs) != 1:
        return "média ponderada pelo valor"
    c = cs[0]
    if not c.inicio or not c.horizonte:
        return "sem prazos na Receita"
    base = min(fim_do_mes(corte), c.horizonte)
    return f"{(base - c.inicio).days} de {(c.horizonte - c.inicio).days} dias até o horizonte"


def _creditos(lanc, periodo: Periodo) -> dict[str, float]:
    base = defaultdict(float)
    for cr, data_baixa, valor in lanc.creditos:
        if periodo.despesa_no_periodo(data_baixa):
            base[cr] += valor
    return base


def _valores(c: Contrato, fat: float, cus: float, credito: float) -> dict:
    liq = fat * (1 - c.tributos)
    pis = c.pis_cofins * (fat - credito)
    adm = c.taxa_adm * fat
    return {
        "bruta": fat,
        "liq": liq,
        "desp": cus,
        "pis": pis,
        "adm": adm,
        "res": liq - cus - pis - adm,
    }


def _somar(linhas: list[dict]) -> dict:
    return {k: sum(x[k] for x in linhas) for k in ("bruta", "liq", "desp", "pis", "adm", "res")}


def _por_grupo(cs: list[Contrato], agrupar: str, fat_c, cus_c, cred_c) -> dict:
    """Resumo agrupado. Contrato com dois coordenadores entra nos dois grupos;
    o total conta cada contrato uma vez."""
    por_cr = {
        c.cr: {
            "cr": c.cr,
            "nome": c.nome,
            "cor": c.cor,
            "cliente": c.cliente,
            "coordenadores": c.coordenadores,
            "taxa": c.taxa_adm,
            **_valores(c, fat_c[c.cr], cus_c[c.cr], cred_c[c.cr]),
        }
        for c in cs
    }
    grupos = defaultdict(list)
    for c in cs:
        if agrupar == "cli":
            chaves = [c.cliente]
        elif agrupar == "coord":
            chaves = c.coordenadores or ["Sem coordenador"]
        else:
            chaves = [f"{c.cr} · {c.nome}"]
        for k in chaves:
            grupos[k].append(por_cr[c.cr])
    linhas = [
        {
            "nome": k,
            "taxas": sorted({x["taxa"] for x in membros}),
            "contratos": membros,
            **_somar(membros),
        }
        for k, membros in grupos.items()
    ]
    linhas.sort(key=lambda g: (-g["bruta"], g["res"]))
    titulo, um, varios = AGRUPAR[agrupar]
    return {
        "agrupar": agrupar,
        "titulo": titulo,
        "singular": um,
        "plural": varios,
        "pis_cofins_txt": _pct_param({c.pis_cofins for c in cs}, casas=2),
        "linhas": linhas,
        "total": _somar(list(por_cr.values())),
    }
