"""Números do painel contra a massa de semente.py (contas feitas à mão)."""

from __future__ import annotations

from datetime import date

import pytest
from werkzeug.datastructures import MultiDict

from app.analise.painel import montar_painel
from app.analise.periodo import Filtro

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
    assert k["alvo_at"] == pytest.approx(280_000 / 1.15)
    assert k["cus"] == pytest.approx(115_000)
    assert k["res"] == pytest.approx(280_000 / 1.15 - 115_000)


def test_universo_e_a_uniao_das_duas_origens(carregado):
    crs = [c["cr"] for c in painel(carregado)["contratos"]]
    assert crs == ["4561", "4602", "4655", "4660"]


def test_cr_so_no_controle_entra_com_receita_zero(carregado):
    d = painel(carregado, cr="4655")
    assert d["cascata"]["fat"] == 0
    assert d["cascata"]["cus"] == pytest.approx(5_000)
    assert d["cascata"]["res"] == pytest.approx(-5_000)
    assert d["sem_receita"] == ["4655"]
    assert d["execucao"] == []  # sem valor nem prazo
    assert d["custo_alvo"]["mk_c"] is None  # divisão por zero vira "—"


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
    assert k["cus"] == pytest.approx(
        65_000
    )  # 15/02 (40 mil) + 20/02 (20 mil) + 05/03 (5 mil, 4655)


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


def test_itens_e_desvio_usam_o_depara(carregado):
    d = painel(carregado, cr="4561")
    nomes = {i["d"]: i["v"] for i in d["itens"]}
    assert nomes == {
        "Engenheiro fiscal (PJ)": pytest.approx(80_000),
        "Veículo locado": pytest.approx(10_000),
    }
    assert {x["codigo"] for x in d["desvios"]} <= {"1.1", "1.2"}


def test_custo_sem_depara_vai_para_nao_classificado(carregado):
    d = painel(carregado, cr="4602")
    assert [i["d"] for i in d["itens"]] == ["Não classificado"]


def test_pendencias_so_abertas_e_pleitos(carregado):
    d = painel(carregado, cr="4561")
    assert [p["assunto"] for p in d["pendencias"]] == ["Renovar seguro-garantia"]
    assert d["pleitos"]["potencial"] == pytest.approx(250_000)
    assert d["pleitos"]["aprovado"] == pytest.approx(200_000)


def test_markup_contratual(carregado):
    a = painel(carregado, cr="4561")["custo_alvo"]
    assert a["mk_c"] == pytest.approx(1_200_000 / 600_000)


def test_coordenador_leitor_ve_so_os_proprios(carregado, leitor, db):
    leitor.nome = "Carlos Menezes"
    db.session.commit()
    crs = [c["cr"] for c in painel(carregado, usuario=leitor)["contratos"]]
    assert crs == ["4561", "4602"]


def test_operador_ve_todos(carregado, operador, db):
    operador.nome = "Carlos Menezes"
    db.session.commit()
    assert len(painel(carregado, usuario=operador)["contratos"]) == 4


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
