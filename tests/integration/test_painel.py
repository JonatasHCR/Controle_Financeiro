"""Números do painel contra a massa de semente.py (contas feitas à mão)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from werkzeug.datastructures import MultiDict

from app.analise.painel import montar_painel
from app.analise.periodo import Filtro
from app.models import CfgItem

pytestmark = pytest.mark.integration

HOJE = date(2026, 3, 31)


def painel(db, usuario=None, **args):
    pares = []
    for chave, valor in args.items():
        for v in valor if isinstance(valor, list) else [valor]:
            pares.append((chave, v))
    return montar_painel(db.session, Filtro.da_query(MultiDict(pares)), usuario, hoje=HOJE)


def test_cascata_todas_as_datas(carregado):
    k = painel(carregado)["cascata"]
    assert k["fat"] == pytest.approx(350_000)
    assert k["trib"] == pytest.approx(70_000)
    assert k["liq"] == pytest.approx(280_000)
    assert k["cus"] == pytest.approx(110_000)
    assert k["res"] == pytest.approx(280_000 - 110_000)
    assert "alvo_at" not in k


def test_universo_sao_os_contratos_da_receita(carregado):
    crs = [c["cr"] for c in painel(carregado)["contratos"]]
    assert crs == ["4561", "4602", "4660"]


def test_cr_so_no_controle_fica_fora(carregado):
    d = painel(carregado, cr="4655")
    assert "4655" not in [c["cr"] for c in d.get("contratos", [])]


def test_contrato_desativado_continua_e_vem_marcado(carregado, db):
    from app.models import RcContrato

    contrato = db.session.scalars(select(RcContrato).where(RcContrato.cr_norm == "4602")).one()
    contrato.ativo = False
    db.session.commit()
    resumo = {c["cr"]: c for c in painel(carregado)["contratos"]}
    assert resumo["4602"]["ativo"] is False and resumo["4561"]["ativo"] is True


def test_cr_so_na_receita_entra_com_custo_zero(carregado):
    d = painel(carregado, cr="4660")
    assert d["cascata"]["cus"] == 0
    assert d["contratos"][0]["despesa"] is False


def test_cr_da_receita_casa_com_o_do_controle_mesmo_com_zero_a_esquerda(carregado):
    """Na Receita está '04602'; no Controle, '4602'."""
    d = painel(carregado, cr="4602")
    assert d["cascata"]["fat"] == pytest.approx(50_000)
    assert d["cascata"]["cus"] == pytest.approx(20_000)


def test_so_o_mes(carregado):
    k = painel(carregado, modo="mes", mes="2026-02")["cascata"]
    assert k["fat"] == pytest.approx(150_000)  # 702 + 801
    assert k["cus"] == pytest.approx(60_000)


def test_acumulado_ate(carregado):
    k = painel(carregado, modo="acum", mes="2026-01")["cascata"]
    assert k["fat"] == pytest.approx(100_000)
    assert k["cus"] == pytest.approx(40_000)


def test_intervalo_de_data_a_data(carregado):
    k = painel(carregado, modo="intervalo", de="2026-02-11", ate="2026-03-10")["cascata"]
    assert k["fat"] == pytest.approx(150_000)  # 801 (15/02) + 703 (10/03)
    assert k["cus"] == pytest.approx(60_000)  # 15/02 (40 mil) + 20/02 (20 mil)


def test_filtros_multiplos_ou_dentro_e_entre(carregado):
    assert [c["cr"] for c in painel(carregado, coordenador="Carlos Menezes")["contratos"]] == [
        "4561",
        "4602",
    ]
    d = painel(carregado, cliente=["Prefeitura Municipal"], coordenador=["Ana Ribeiro"])
    assert [c["cr"] for c in d["contratos"]] == ["4660"]
    assert (
        painel(carregado, cliente="Companhia de Saneamento", coordenador="Nadia")["vazio"] is True
    )


def test_rotulos_todos_ou_selecionados(carregado):
    r = painel(carregado)["meta"]["rotulos"]
    assert (r["cliente"], r["coordenador"], r["titulo"]) == ("Todos", "Todos", "")
    assert r["contratos"].startswith("Todos")
    r = painel(carregado, cr=["4561", "4602"])["meta"]["rotulos"]
    assert r["titulo"] == "Contratos 4561, 4602"
    assert painel(carregado, cr="4561")["meta"]["rotulos"]["titulo"] == "4561 · Sistema adutor"


def test_recebimento_e_nfs_em_aberto(carregado):
    r = painel(carregado)["recebimento"]
    assert r["pago"] == pytest.approx(250_000)
    assert r["aberto"] == pytest.approx(100_000)
    assert [g["cr"] for g in r["abertas"]] == ["4561"]
    assert r["abertas"][0]["nfs"][0]["nf"] == "703"


def test_valor_inicial_e_aditivos_da_receita(carregado):
    c = painel(carregado, cr="4561")["contratos"][0]
    assert c["valor_inicial"] == pytest.approx(1_000_000)
    assert c["aditivos"] == pytest.approx(200_000)


def test_itens_usam_o_depara(carregado):
    d = painel(carregado, cr="4561")
    nomes = {i["d"]: i["v"] for i in d["itens"]}
    assert nomes == {
        "Engenheiro fiscal (PJ)": pytest.approx(80_000),
        "Veículo locado": pytest.approx(10_000),
    }
    assert "desvios" not in d and "custo_alvo" not in d and "prazos" not in d


def test_natureza_sem_ligacao_vira_item_com_o_proprio_nome(carregado):
    d = painel(carregado, cr="4602")
    assert "Não classificado" not in [i["d"] for i in d["itens"]]
    assert all(i["v"] > 0 for i in d["itens"])


def test_varias_naturezas_no_mesmo_item_somam(carregado, db):
    from app.models import CdNatureza, DeparaItem

    naturezas = db.session.scalars(select(CdNatureza.nome_norm)).all()
    for natureza in naturezas:
        db.session.merge(DeparaItem(cr_norm="4602", natureza_nome_norm=natureza, item_codigo="9.9"))
    db.session.add(CfgItem(cr_norm="4602", codigo="9.9", descricao="Tudo junto", custo_alvo=1))
    db.session.commit()
    d = painel(carregado, cr="4602")
    assert [i["d"] for i in d["itens"]] == ["Tudo junto"]


def test_pendencias_so_abertas_e_pleitos(carregado):
    d = painel(carregado, cr="4561")
    assert [p["assunto"] for p in d["pendencias"]] == ["Renovar seguro-garantia"]
    assert d["pleitos"]["potencial"] == pytest.approx(250_000)
    assert d["pleitos"]["aprovado"] == pytest.approx(200_000)


def test_coordenador_leitor_ve_so_os_proprios(carregado, leitor, db):
    leitor.nome = "Carlos Menezes"
    db.session.commit()
    crs = [c["cr"] for c in painel(carregado, usuario=leitor)["contratos"]]
    assert crs == ["4561", "4602"]


def test_operador_ve_todos(carregado, operador, db):
    operador.nome = "Carlos Menezes"
    db.session.commit()
    assert len(painel(carregado, usuario=operador)["contratos"]) == 3


# --- rotas ------------------------------------------------------------------


def test_pagina_exige_login(client):
    assert client.get("/").status_code == 302


def test_pagina_e_json(entrar, leitor, carregado):
    cliente = entrar(leitor)
    corpo = cliente.get("/").get_data(as_text=True)
    assert 'id="dados-iniciais"' in corpo and "c-cascata" in corpo
    dados = cliente.get("/api/painel?cr=4561").get_json()
    assert dados["contratos"][0]["cr"] == "4561"


def test_pagina_sem_handler_inline(entrar, leitor, carregado):
    import re

    corpo = entrar(leitor).get("/").get_data(as_text=True)
    assert not re.search(r"\son(click|change|submit|input)\s*=", corpo)


def test_leitor_nao_ve_abas_de_operador_e_admin(entrar, leitor, carregado):
    corpo = entrar(leitor).get("/").get_data(as_text=True)
    assert "/configuracao" not in corpo and "/administracao" not in corpo


# --- resumo agrupado ------------------------------------------------------------
# Padrão: tributos 20%, taxa adm. 15%, PIS/COFINS 9,25%.
# 4561: bruta 300 mil, líquida 240 mil, custo 90 mil, PIS 27.750, ADM 45 mil → 77.250
# 4602: bruta 50 mil, líquida 40 mil, custo 20 mil, PIS 4.625, ADM 7.500 → 7.875


def test_resumo_por_contratante(carregado):
    g = painel(carregado)["por_grupo"]
    assert g["agrupar"] == "cli" and g["titulo"] == "Contratante"
    linhas = {x["nome"]: x for x in g["linhas"]}
    assert list(linhas) == ["Companhia de Saneamento", "Prefeitura Municipal"]
    cia = linhas["Companhia de Saneamento"]
    assert cia["bruta"] == pytest.approx(300_000)
    assert cia["liq"] == pytest.approx(240_000)
    assert cia["desp"] == pytest.approx(90_000)
    assert cia["pis"] == pytest.approx(27_750)
    assert cia["adm"] == pytest.approx(45_000)
    assert cia["res"] == pytest.approx(77_250)
    assert cia["taxas"] == [pytest.approx(0.15)]
    pref = linhas["Prefeitura Municipal"]
    assert [c["cr"] for c in pref["contratos"]] == ["4602", "4660"]
    assert pref["res"] == pytest.approx(7_875)
    assert g["total"]["res"] == pytest.approx(77_250 + 7_875)


def test_resumo_por_coordenador_conta_o_contrato_uma_vez_no_total(carregado):
    g = painel(carregado, agrupar="coord")["por_grupo"]
    linhas = {x["nome"]: [c["cr"] for c in x["contratos"]] for x in g["linhas"]}
    assert linhas == {"Ana Ribeiro": ["4561", "4660"], "Carlos Menezes": ["4561", "4602"]}
    assert g["total"]["bruta"] == pytest.approx(350_000)


def test_resumo_por_centro_de_custo(carregado):
    g = painel(carregado, agrupar="cr")["por_grupo"]
    assert [x["nome"] for x in g["linhas"]] == [
        "4561 · Sistema adutor",
        "4602 · Drenagem",
        "4660 · Orla",
    ]
    assert painel(carregado, agrupar="xyz")["por_grupo"]["agrupar"] == "cli"


def test_credito_de_pis_cofins_so_das_naturezas_marcadas(carregado, db):
    from app.models import CfgNaturezaCredito

    db.session.add(CfgNaturezaCredito(natureza_nome_norm="LOCACAO DE VEICULOS"))
    db.session.commit()
    g = painel(carregado, agrupar="cr")["por_grupo"]
    c4561 = next(x for x in g["linhas"] if x["nome"].startswith("4561"))
    assert c4561["pis"] == pytest.approx(0.0925 * (300_000 - 10_000))


def test_pis_cofins_de_cada_contrato(carregado, db):
    from decimal import Decimal

    from app.models import Parametros

    db.session.add(
        Parametros(
            cr_norm="4561",
            tributos=Decimal("0.2"),
            taxa_adm=Decimal("0.15"),
            pis_cofins=Decimal("0.0365"),
        )
    )
    db.session.commit()
    g = painel(carregado, agrupar="cr")["por_grupo"]
    c4561 = next(x for x in g["linhas"] if x["nome"].startswith("4561"))
    assert c4561["pis"] == pytest.approx(0.0365 * 300_000)
    assert g["pis_cofins_txt"] == "por contrato"


def test_taxa_adm_de_cada_contrato(carregado, db):
    from decimal import Decimal

    from app.models import Parametros

    db.session.add(Parametros(cr_norm="4602", tributos=Decimal("0.2"), taxa_adm=Decimal("0.10")))
    db.session.commit()
    pref = next(x for x in painel(carregado)["por_grupo"]["linhas"] if x["nome"].startswith("Pref"))
    assert pref["adm"] == pytest.approx(5_000)
    assert pref["taxas"] == [pytest.approx(0.10), pytest.approx(0.15)]


# --- NFs não pagas ---------------------------------------------------------------


def test_nfs_nao_pagas_filtradas_no_servidor(carregado):
    d = painel(carregado, nf="open")
    assert [n["numero"] for n in d["nfs"]["lista"]] == ["703"]
    assert d["nfs"]["so_abertas"] is True
    assert d["meta"]["estado"] == {"nf": "open", "agrupar": "cli"}
    assert d["meta"]["rotulos"]["nf"] == "Só não pagas"
    assert len(painel(carregado)["nfs"]["lista"]) == 4


def test_impressao_respeita_nfs_nao_pagas_e_agrupamento(entrar, leitor, carregado, app):
    from app.relatorio.rotas import _assinador

    cliente = entrar(leitor)
    with app.test_request_context():
        token = _assinador().dumps({"u": leitor.id, "q": "nf=open&agrupar=coord"})
    corpo = cliente.get(f"/relatorio/impressao?t={token}").get_data(as_text=True)
    import re

    assert re.search(r'"nf":\s*"open"', corpo) and re.search(r'"agrupar":\s*"coord"', corpo)


def test_percentual_dos_tributos_mantem_as_casas(carregado, db):
    from decimal import Decimal

    from app.models import Parametros

    db.session.add(Parametros(cr_norm="*", tributos=Decimal("0.1188"), taxa_adm=Decimal("0.125")))
    db.session.commit()
    assert painel(carregado)["cascata"]["tributos_txt"] == "11,88%"
    db.session.get(Parametros, "*").tributos = Decimal("0.2")
    db.session.commit()
    assert painel(carregado)["cascata"]["tributos_txt"] == "20%"
