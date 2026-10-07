"""Monta tudo o que a tela, a impressão e o PDF mostram.

Um objeto só (dict serializável), para que os três números batam sempre.
Fórmulas as do dashboard de fiscalização: líquida = bruta − tributos;
custo-alvo atual = líquida ÷ (1 + taxa adm.); BDI = (1 + taxa) ÷ (1 − tributos).
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
    meses_entre,
    rotulo_mes,
    ym,
)
from app.models import PERFIS, CfgItem


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
    }


def _tempo(c: Contrato, corte: str) -> float:
    if not c.inicio or not c.horizonte:
        return 0.0
    total = (c.horizonte - c.inicio).days
    if total <= 0:
        return 1.0
    base = min(fim_do_mes(corte), fim_do_mes(ym(c.horizonte)))
    return max(0.0, min(1.0, (base - c.inicio).days / total))


def _ultimo_mes_com_dado(c: Contrato, corte: str) -> str:
    fim = ym(c.fim_execucao or c.fim_vigencia) if c.receita else None
    return min(corte, fim) if fim else corte


def _item_calc(
    c: Contrato, itens: list[CfgItem], real_por_item: dict[str, float], corte: str
) -> list[dict]:
    """Custo-alvo projetado, custo projetado e desvio de cada item (sempre acumulado)."""
    k = _ultimo_mes_com_dado(c, corte)
    inicio = ym(c.inicio) if c.inicio else None
    meses_corridos = meses_entre(inicio, k) + 1 if inicio else 1
    meses_restantes = max(0, meses_entre(k, ym(c.horizonte))) if c.horizonte else 0
    linhas = []
    codigos = set()
    for it in itens:
        codigos.add(it.codigo)
        real = real_por_item.get(it.codigo, 0.0)
        alvo = float(it.custo_alvo or 0)
        alvo_proj = float(it.custo_alvo_projetado) if it.custo_alvo_projetado is not None else alvo
        ritmo = real / max(1, meses_corridos)
        proj = real if c.status == "CONCLUÍDO" else real + ritmo * meses_restantes
        linhas.append(
            {
                "cr": c.cr,
                "codigo": it.codigo,
                "d": it.descricao,
                "alvo": alvo,
                "alvo_u": alvo_proj,
                "real": real,
                "proj": proj,
                "desv": alvo_proj - proj,
            }
        )
    # Natureza sem ligação é item próprio, sem custo-alvo; código de item que
    # sumiu da configuração aparece com o código, para alguém religar.
    for cod, real in sorted(real_por_item.items(), key=lambda par: -par[1]):
        if cod in codigos or not real:
            continue
        ritmo = real / max(1, meses_corridos)
        proj = real if c.status == "CONCLUÍDO" else real + ritmo * meses_restantes
        linhas.append(
            {
                "cr": c.cr,
                "codigo": cod,
                "d": nome_do_item(cod),
                "alvo": 0.0,
                "alvo_u": 0.0,
                "real": real,
                "proj": proj,
                "desv": -proj,
                "sem_alvo": True,
            }
        )
    return linhas


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
    alvo_at = sum(fat_c[c.cr] * (1 - c.tributos) / (1 + c.taxa_adm) for c in cs)
    cascata = {
        "valor": valor_total,
        "fat": fat,
        "trib": trib,
        "liq": liq,
        "tx": liq - alvo_at,
        "alvo_at": alvo_at,
        "cus": cus,
        "res": alvo_at - cus,
        "n_nfs": len(nfs_periodo),
        "tributos_txt": _pct_param({c.tributos for c in cs}),
        "taxa_txt": _pct_param({c.taxa_adm for c in cs}),
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

    # --- itens, tendência e markup (acumulado até o corte) ------------------------
    real_acum = defaultdict(lambda: defaultdict(float))
    real_periodo = defaultdict(float)
    for cr, data_baixa, item, valor in lanc.custos:
        if ym(data_baixa) <= _ultimo_mes_com_dado(por_cr[cr], corte):
            real_acum[cr][item] += valor
        if periodo.despesa_no_periodo(data_baixa):
            real_periodo[(cr, item)] += valor
    calc = {c.cr: _item_calc(c, lanc.itens.get(c.cr, []), real_acum[c.cr], corte) for c in cs}
    todos_itens = [i for linhas in calc.values() for i in linhas]
    alvo = sum(i["alvo"] for i in todos_itens)
    alvo_u = sum(i["alvo_u"] for i in todos_itens)
    proj = sum(i["proj"] for i in todos_itens)
    desv = sum(i["desv"] for i in todos_itens)
    rec_proj = sum(i["alvo_u"] * por_cr[i["cr"]].bdi for i in todos_itens)
    custo_alvo = {
        "alvo": alvo,
        "alvo_u": alvo_u,
        "proj": proj,
        "desv": desv,
        "mk_c": valor_total / alvo if alvo else None,
        "mk_a": fat / cus if cus else None,
        "mk_f": rec_proj / proj if proj else None,
        **_serie_resultado(cs, lanc, inicio_geral, corte, desv),
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
        rp = sum(i["alvo_u"] for i in calc[c.cr]) * c.bdi
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
                "cov": rp / c.valor if c.valor else 0.0,
                "rp": rp,
                "classe": classe,
                "texto": texto,
                "despesa": c.despesa,
            }
        )

    # --- custo e desvio por item -------------------------------------------------------
    nomes_item = {(i["cr"], i["codigo"]): i["d"] for i in todos_itens}
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
    desvios = sorted(
        # Item sem custo-alvo (natureza sem ligação) não tem desvio a comparar.
        (i for i in todos_itens if abs(i["desv"]) > 0.5 and not i.get("sem_alvo")),
        key=lambda i: -abs(i["desv"]),
    )[:10]
    desvios.sort(key=lambda i: -i["desv"])

    # --- prazos, pendências, pleitos, NFs ------------------------------------------------
    prazos = [
        _ficha(c)
        for c in sorted(
            (c for c in cs if c.inicio and c.fim_execucao), key=lambda c: c.fim_execucao
        )
    ]
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
    lista_nfs = sorted(nfs_periodo, key=lambda n: (n["competencia"], n["numero"]), reverse=True)

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
        "custo_alvo": custo_alvo,
        "execucao": execucao,
        "sem_receita": [c.cr for c in cs if not c.receita],
        "itens": itens_periodo,
        "desvios": desvios,
        "prazos": prazos,
        "riscos": [
            {"cr": c.cr, "dias": (c.fim_execucao - c.fim_vigencia).days}
            for c in cs
            if c.fim_vigencia and c.fim_execucao and c.fim_vigencia < c.fim_execucao
        ],
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
            "a_receber": aberto,
            "n_a_receber": sum(1 for n in nfs_periodo if not n["paga"]),
            "pago": pago,
            "n_pago": recebimento["n_pago"],
        },
    }


def _pct_param(valores: set[float]) -> str:
    if len(valores) == 1:
        return f"{next(iter(valores)) * 100:.0f}%".replace(".", ",")
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


def _serie_resultado(cs, lanc, inicio: str, corte: str, final: float) -> dict:
    """Resultado acumulado mês a mês (NFs ÷ BDI − custo) e tendência linear até o horizonte."""
    bdi = {c.cr: c.bdi for c in cs}
    meses = _intervalo_meses(inicio, corte)
    alvo_mes = defaultdict(float)
    for n in lanc.nfs:
        alvo_mes[n["competencia"]] += n["valor"] / bdi[n["cr"]]
    cus_mes = defaultdict(float)
    for _cr, d, _i, v in lanc.custos:
        cus_mes[ym(d)] += v
    atual, acum = [], 0.0
    for m in meses:
        acum += alvo_mes[m] - cus_mes[m]
        atual.append(acum)
    horizontes = sorted(ym(c.horizonte) for c in cs if c.horizonte)
    fim = horizontes[-1] if horizontes else corte
    futuros = _intervalo_meses(add_meses(corte, 1), fim) if fim > corte else []
    ultimo = atual[-1] if atual else 0.0
    tendencia = [ultimo + (final - ultimo) * (i + 1) / len(futuros) for i in range(len(futuros))]
    com_h = [c for c in cs if c.horizonte]
    return {
        "res_rotulos": [rotulo_mes(m) for m in meses + futuros],
        "res_atual": atual,
        "res_tendencia": tendencia,
        "horizontes": [{"cr": c.cr, "mes": rotulo_mes(ym(c.horizonte))} for c in com_h],
        "horizonte_final": rotulo_mes(fim),
    }


def _tempo_txt(cs: list[Contrato], corte: str) -> str:
    if len(cs) != 1:
        return "média ponderada pelo valor"
    c = cs[0]
    if not c.inicio or not c.horizonte:
        return "sem prazos na Receita"
    base = min(fim_do_mes(corte), c.horizonte)
    return f"{(base - c.inicio).days} de {(c.horizonte - c.inicio).days} dias até o horizonte"
