"""Regras de período e de normalização (sem banco)."""

from __future__ import annotations

from datetime import date

import pytest
from werkzeug.datastructures import MultiDict

from app.analise.normalizar import cr_norm, nome_norm
from app.analise.periodo import Filtro, Periodo, add_meses, fim_do_mes, meses_entre, rotulo_mes

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "entrada, saida",
    [
        ("4561", "4561"),
        ("04561", "4561"),
        (" 4561 ", "4561"),
        ("000", "0"),
        ("ab-12", "AB-12"),
        ("", ""),
        (None, ""),
    ],
)
def test_cr_norm(entrada, saida):
    assert cr_norm(entrada) == saida


def test_nome_norm_ignora_acento_caixa_e_espaco():
    assert nome_norm("  Locação   de veículos ") == nome_norm("LOCACAO DE VEICULOS")


def test_aritmetica_de_meses():
    assert add_meses("2026-11", 3) == "2027-02"
    assert add_meses("2026-01", -1) == "2025-12"
    assert meses_entre("2025-12", "2026-03") == 3
    assert fim_do_mes("2024-02") == date(2024, 2, 29)
    assert rotulo_mes("2026-09") == "set/26"


def _filtro(**args):
    return Filtro.da_query(MultiDict(args))


def test_filtro_le_listas_e_ignora_lixo():
    f = Filtro.da_query(
        MultiDict(
            [("cliente", "A"), ("cliente", "B"), ("cr", ""), ("modo", "xyz"), ("mes", "2026-13")]
        )
    )
    assert f.clientes == ["A", "B"]
    assert f.crs == []
    assert f.modo == "todas"
    assert f.mes is None


def test_data_inicial_depois_da_final_e_trocada():
    f = _filtro(modo="intervalo", de="2026-05-10", ate="2026-01-01")
    assert (f.de, f.ate) == (date(2026, 1, 1), date(2026, 5, 10))


def test_so_o_mes_sem_mes_vai_para_o_mais_recente_da_base():
    p = Periodo.resolver(_filtro(modo="mes"), "2026-09", None, None)
    assert p.mes == "2026-09"
    assert p.mes_no_periodo("2026-09") and not p.mes_no_periodo("2026-08")


def test_acumulado_ate_o_mes():
    p = Periodo.resolver(_filtro(modo="acum", mes="2026-03"), "2026-09", None, None)
    assert p.corte == "2026-03"
    assert p.mes_no_periodo("2025-01") and not p.mes_no_periodo("2026-04")


def test_todas_as_datas_vai_ate_a_base():
    p = Periodo.resolver(_filtro(), "2026-09", None, None)
    assert p.corte == "2026-09"
    assert p.mes_no_periodo("2020-01") and not p.mes_no_periodo("2026-10")


def test_intervalo_por_data_nf_pela_emissao_e_despesa_pela_baixa():
    p = Periodo.resolver(
        _filtro(modo="intervalo", de="2026-02-10", ate="2026-03-05"), "2026-09", None, None
    )
    assert p.nf_no_periodo("2026-01", date(2026, 2, 10))  # competência não importa no intervalo
    assert not p.nf_no_periodo("2026-02", date(2026, 2, 9))
    assert p.despesa_no_periodo(date(2026, 3, 5)) and not p.despesa_no_periodo(date(2026, 3, 6))
    assert p.corte == "2026-03"


def test_intervalo_sem_limite_maximo_na_data_final():
    p = Periodo.resolver(
        _filtro(modo="intervalo", de="2026-01-01", ate="2030-12-31"), "2026-09", None, None
    )
    assert p.ate == date(2030, 12, 31)
    assert p.corte == "2026-09"  # posição de execução não passa da base


def test_intervalo_nao_comeca_antes_do_primeiro_dado():
    p = Periodo.resolver(
        _filtro(modo="intervalo", de="2020-01-01", ate="2026-03-01"),
        "2026-09",
        date(2025, 1, 15),
        date(2026, 9, 30),
    )
    assert p.de == date(2025, 1, 15)


def test_intervalo_padrao_onze_meses_antes_ate_o_ultimo_dado():
    p = Periodo.resolver(_filtro(modo="intervalo"), "2026-09", date(2020, 1, 1), date(2026, 10, 6))
    assert (p.de, p.ate) == (date(2025, 11, 1), date(2026, 10, 6))


def test_filtro_le_nfs_e_agrupamento():
    f = Filtro.da_query(MultiDict([("nf", "open"), ("agrupar", "coord")]))
    assert (f.nf, f.agrupar) == ("open", "coord")
    f = Filtro.da_query(MultiDict([("nf", "x"), ("agrupar", "y")]))
    assert (f.nf, f.agrupar) == ("all", "cli")
