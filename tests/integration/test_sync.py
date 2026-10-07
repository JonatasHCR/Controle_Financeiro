"""Sincronização com a Receita e o Controle de Despesa (APIs simuladas)."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from sqlalchemy import func, select

from app.models import (
    CdCentro,
    CdDespesa,
    RcContrato,
    RcContratoCoordenador,
    RcNf,
    RcPrevisao,
    SyncExecucao,
)
from app.sync.executor import sincronizar

pytestmark = pytest.mark.integration

RECEITA = "http://receita.teste/api/v1"
CONTROLE = "http://controle.teste/api/v1"


@pytest.fixture
def origens(app, db):
    app.config.update(
        RECEITA_API_URL=RECEITA,
        RECEITA_API_TOKEN="t1",
        CONTROLE_API_URL=CONTROLE,
        CONTROLE_API_TOKEN="t2",
        SYNC_HORA_COMPLETA=0,
    )
    estado = {
        "clients": [{"id": 1, "name": "Prefeitura", "full_name": "Prefeitura Municipal"}],
        "cost_centers": [
            {
                "id": 1,
                "cr_code": "04561",
                "description": "Adutor",
                "contract_number": "1/24",
                "coordinator": "Ana / Bia",
                "coordinator_list": ["Ana", "Bia"],
                "start_date": "2025-01-01",
                "end_date": "2026-12-31",
                "value": "1000.00",
                "participation": "1.0",
                "client_id": 1,
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
        "invoices": [
            {
                "id": 1,
                "cost_center_id": 1,
                "number": "10",
                "issued_at": "2026-01-10",
                "kind": "principal",
                "value": "100.50",
                "updated_at": "2026-01-10T10:00:00Z",
            }
        ],
        "receipts": [],
        "adjustments": [],
        "forecast_entries": [
            {
                "id": 1,
                "cost_center_id": 1,
                "month_year": "JUNHO/2026",
                "forecasted_total": "50.0",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
        "deletions": [],
        "despesas": [
            {
                "id": 1,
                "centro_custo_id": 9,
                "fornecedor_id": 1,
                "natureza_id": 1,
                "data_baixa": "2026-01-15",
                "valor_original": "10.00",
                "valor_baixado": "10.00",
                "atualizado_em": "2026-01-15T00:00:00+00:00",
            },
            {
                "id": 2,
                "centro_custo_id": 9,
                "fornecedor_id": 1,
                "natureza_id": 1,
                "data_baixa": "2026-01-16",
                "valor_original": "5.00",
                "valor_baixado": "5.00",
                "atualizado_em": "2026-01-16T00:00:00+00:00",
            },
        ],
        "exclusoes": [],
        "centros": [
            {"id": 9, "codigo": "4561", "nome": "Adutor", "ativo": True},
            {"id": 7, "codigo": "0777", "nome": "Sem contrato", "ativo": True},
        ],
        "chamadas": [],
        "falhar_controle": False,
    }

    def lista(chave):
        def resposta(req):
            estado["chamadas"].append(req.url)
            consulta = {k: v[0] for k, v in parse_qs(urlparse(req.url).query).items()}
            itens = estado[chave]
            # Como as APIs de verdade: só o que mudou depois da marca pedida.
            desde = consulta.get("updated_since") or consulta.get("since")
            if desde:
                itens = [x for x in itens if _instante(_marca_do(x)) > _instante(desde)]
            if "centro_ids" in consulta or (chave == "despesas" and "centro_ids" in req.url):
                centros = {int(c) for c in consulta.get("centro_ids", "").split(",") if c}
                itens = [x for x in itens if x["centro_custo_id"] in centros]
            ultimo = itens[-1] if itens else {}
            marca = _marca_do(ultimo)
            return (
                200,
                {},
                _json({chave: itens, "watermark": marca, "count": len(itens), "has_more": False}),
            )

        return resposta

    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        for recurso in (
            "clients",
            "cost_centers",
            "invoices",
            "receipts",
            "adjustments",
            "forecast_entries",
            "deletions",
        ):
            mock.add_callback(
                responses.GET, re.compile(rf"{RECEITA}/{recurso}(\?.*)?$"), callback=lista(recurso)
            )
        mock.add_callback(
            responses.GET,
            re.compile(rf"{RECEITA}/status$"),
            callback=lambda req: (
                200,
                {},
                _json(
                    {
                        "invoices": {
                            "count": len(estado["invoices"]),
                            "sum": str(sum(Decimal(n["value"]) for n in estado["invoices"])),
                        },
                        "receipts": {"count": len(estado["receipts"])},
                    }
                ),
            ),
        )

        def controle(chave):
            def resposta(req):
                if estado["falhar_controle"]:
                    return 500, {}, "erro"
                return lista(chave)(req)

            return resposta

        mock.add_callback(
            responses.GET,
            re.compile(rf"{CONTROLE}/despesas(\?.*)?$"),
            callback=controle("despesas"),
        )
        mock.add_callback(
            responses.GET,
            re.compile(rf"{CONTROLE}/despesas/exclusoes(\?.*)?$"),
            callback=controle("exclusoes"),
        )
        mock.add_callback(
            responses.GET,
            re.compile(rf"{CONTROLE}/despesas/ids(\?.*)?$"),
            callback=lambda req: (
                200,
                {},
                _json({"ids": [d["id"] for d in _dos_centros(estado["despesas"], req)]}),
            ),
        )
        mock.add_callback(
            responses.GET,
            f"{CONTROLE}/centros_custo",
            callback=lambda req: (200, {}, _json({"centros_custo": estado["centros"]})),
        )
        mock.add(
            responses.GET,
            f"{CONTROLE}/fornecedores",
            json={"fornecedores": [{"id": 1, "nome": "F", "ativo": True}]},
        )
        mock.add(
            responses.GET,
            f"{CONTROLE}/naturezas",
            json={"naturezas": [{"id": 1, "nome": "Locação de veículos", "ativo": True}]},
        )
        mock.add_callback(
            responses.GET,
            re.compile(rf"{CONTROLE}/status(\?.*)?$"),
            callback=lambda req: (
                200,
                {},
                _json(
                    {
                        "despesas": {
                            "count": len(_dos_centros(estado["despesas"], req)),
                            "sum_valor_baixado": str(
                                sum(
                                    Decimal(d["valor_baixado"])
                                    for d in _dos_centros(estado["despesas"], req)
                                )
                            ),
                        }
                    }
                ),
            ),
        )
        yield estado


def _dos_centros(itens: list[dict], req) -> list[dict]:
    consulta = parse_qs(urlparse(req.url).query)
    if "centro_ids" not in consulta:
        return itens
    centros = {int(c) for c in consulta["centro_ids"][0].split(",") if c}
    return [x for x in itens if x["centro_custo_id"] in centros]


def _marca_do(item: dict):
    chaves = ("updated_at", "atualizado_em", "deleted_at", "excluida_em")
    return next((item[k] for k in chaves if k in item), None)


def _instante(texto: str) -> datetime:
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


def _json(valor) -> str:
    import json

    return json.dumps(valor)


def _contar(db, modelo) -> int:
    return db.session.scalar(select(func.count()).select_from(modelo))


def test_primeira_carga(origens, db):
    execucao = sincronizar(disparo="manual")
    assert execucao.status == "ok"
    contrato = db.session.scalars(select(RcContrato)).one()
    assert (contrato.cr_code, contrato.cr_norm, float(contrato.valor)) == ("04561", "4561", 1000.0)
    assert {c.nome for c in db.session.scalars(select(RcContratoCoordenador))} == {"Ana", "Bia"}
    assert float(db.session.scalars(select(RcNf)).one().valor) == 100.50
    assert str(db.session.scalars(select(RcPrevisao)).one().competencia) == "2026-06-01"
    assert _contar(db, CdDespesa) == 2


def test_segunda_rodada_nao_duplica(origens, db):
    sincronizar()
    sincronizar()
    assert _contar(db, RcNf) == 1 and _contar(db, CdDespesa) == 2


def test_exclusao_no_controle_some_aqui(origens, db):
    sincronizar()
    origens["despesas"] = origens["despesas"][:1]
    origens["exclusoes"] = [{"id": 2, "excluida_em": "2026-02-01T00:00:00+00:00"}]
    sincronizar()
    assert _contar(db, CdDespesa) == 1


def test_reconciliacao_pega_exclusao_sem_rastro(origens, db):
    """Restauração de backup no Controle: some sem passar pela trigger."""
    sincronizar()
    origens["despesas"] = origens["despesas"][:1]
    sincronizar()
    assert _contar(db, CdDespesa) == 1


def test_nf_apagada_na_receita_some_aqui(origens, db):
    sincronizar()
    origens["invoices"] = []
    origens["deletions"] = [
        {"item_type": "Invoice", "item_id": 1, "deleted_at": "2026-02-01T00:00:00Z"}
    ]
    sincronizar()
    assert _contar(db, RcNf) == 0


def test_contrato_apagado_na_receita_some_na_recarga(origens, db):
    sincronizar()
    origens["cost_centers"] = []
    sincronizar()
    assert _contar(db, RcContrato) == 0


def test_uma_origem_fora_do_ar_nao_derruba_a_outra(origens, db):
    origens["falhar_controle"] = True
    execucao = sincronizar()
    assert execucao.status == "parcial"
    assert "controle" in execucao.erro
    assert _contar(db, RcNf) == 1 and _contar(db, CdDespesa) == 0


def test_origem_nao_configurada_fica_registrada(app, db):
    app.config.update(RECEITA_API_URL="", CONTROLE_API_URL="")
    execucao = sincronizar()
    assert execucao.contagens == {"receita": "não configurada", "controle": "não configurada"}


def test_trava_impede_duas_rodadas(origens, db):
    from sqlalchemy import text

    from app.sync.executor import CHAVE_TRAVA

    outra = db.engine.connect()
    try:
        outra.execute(text("SELECT pg_advisory_lock(:k)"), {"k": CHAVE_TRAVA})
        assert sincronizar() is None
    finally:
        outra.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": CHAVE_TRAVA})
        outra.close()


def test_incremental_pede_desde_a_marca(origens, db):
    sincronizar(completo=False)
    origens["chamadas"].clear()
    sincronizar(completo=False)
    pedidos_nf = [u for u in origens["chamadas"] if "/invoices" in u]
    assert pedidos_nf and all("updated_since" in u for u in pedidos_nf)


def test_sincronizar_agora_so_admin(origens, entrar, admin, operador, db):
    assert entrar(operador).post("/administracao/sincronizar").status_code == 403
    resposta = entrar(admin).post("/administracao/sincronizar")
    assert resposta.status_code == 302
    assert db.session.scalars(select(SyncExecucao)).one().disparo == "manual"


def test_valor_alterado_sem_mudar_a_marca_e_pego_pela_soma(origens, db):
    """A quantidade bate, mas o valor não: só a soma enxerga."""
    sincronizar(completo=False)
    origens["despesas"][0]["valor_baixado"] = "99.00"  # sem mexer em atualizado_em
    execucao = sincronizar(completo=False)
    assert execucao.contagens["controle"].get("reconciliado_soma") is True
    valores = sorted(float(d.valor_baixado) for d in db.session.scalars(select(CdDespesa)))
    assert valores == [5.0, 99.0]


def test_exclusoes_pedem_com_folga(origens, db):
    origens["exclusoes"] = [{"id": 99, "excluida_em": "2026-02-01T12:00:00+00:00"}]
    sincronizar()
    origens["chamadas"].clear()
    sincronizar()
    pedido = next(u for u in origens["chamadas"] if "/despesas/exclusoes" in u)
    since = parse_qs(urlparse(pedido).query)["since"][0]
    assert _instante(since) == _instante("2026-02-01T11:50:00+00:00")


# --- paginação ------------------------------------------------------------------


def test_paginacao_segue_a_ultima_linha_lida():
    from app.sync.cliente import ClienteApi

    with responses.RequestsMock() as mock:
        pedidos = []

        def pagina(req):
            consulta = parse_qs(urlparse(req.url).query)
            pedidos.append(consulta)
            if "after_id" not in consulta:
                corpo = {
                    "itens": [{"id": 1}, {"id": 2}],
                    "watermark": "2026-01-01T00:00:00+00:00",
                    "last_id": 2,
                    "has_more": True,
                }
            else:
                corpo = {
                    "itens": [{"id": 3}],
                    "watermark": "2026-01-02T00:00:00+00:00",
                    "last_id": 3,
                    "has_more": False,
                }
            return 200, {}, _json(corpo)

        mock.add_callback(responses.GET, re.compile(rf"{CONTROLE}/itens(\?.*)?$"), callback=pagina)
        cliente = ClienteApi(CONTROLE, "t")
        ids = [i["id"] for p, _ in cliente.paginar("itens", "itens", limite=2) for i in p]

    assert ids == [1, 2, 3]
    assert pedidos[1]["after_id"] == ["2"]
    assert pedidos[1]["updated_since"] == ["2026-01-01T00:00:00+00:00"]
    assert "offset" not in pedidos[1]


def test_api_que_ignora_a_paginacao_nao_prende_o_sync():
    """Antes da correção, /exclusoes devolvia sempre a 1ª página e o sync girava para sempre."""
    from app.sync.cliente import ClienteApi, ErroDeSync

    with responses.RequestsMock() as mock:
        mock.add(
            responses.GET,
            re.compile(rf"{CONTROLE}/exclusoes(\?.*)?$"),
            json={"exclusoes": [{"id": 1}, {"id": 2}], "watermark": None, "has_more": True},
        )
        cliente = ClienteApi(CONTROLE, "t")
        with pytest.raises(ErroDeSync, match="mesma página"):
            for _ in cliente.paginar("exclusoes", "exclusoes", limite=2, marca="since"):
                pass


# --- só os CRs com contrato na Receita --------------------------------------------


def _despesa(id_, centro, data="2026-01-20"):
    return {
        "id": id_,
        "centro_custo_id": centro,
        "fornecedor_id": 1,
        "natureza_id": 1,
        "data_baixa": data,
        "valor_original": "1.00",
        "valor_baixado": "1.00",
        "atualizado_em": f"{data}T00:00:00+00:00",
    }


def test_despesa_de_centro_sem_contrato_nao_entra(origens, db):
    origens["despesas"].append(_despesa(50, centro=7))
    sincronizar()
    centros = set(db.session.scalars(select(CdDespesa.centro_origem_id)))
    assert centros == {9}
    # nem o cadastro do centro sem contrato fica guardado
    assert set(db.session.scalars(select(CdCentro.origem_id))) == {9}
    pedido = next(u for u in origens["chamadas"] if "/despesas?" in u)
    assert parse_qs(urlparse(pedido).query)["centro_ids"] == ["9"]


def test_contrato_novo_na_receita_traz_o_historico_do_centro(origens, db):
    origens["despesas"].append(_despesa(50, centro=7, data="2025-03-01"))  # antiga
    sincronizar(completo=False)
    assert _contar(db, CdDespesa) == 2

    origens["cost_centers"].append(
        {
            **origens["cost_centers"][0],
            "id": 2,
            "cr_code": "777",
            "updated_at": "2026-03-01T00:00:00Z",
        }
    )
    sincronizar(completo=False)
    assert db.session.scalars(select(CdDespesa).where(CdDespesa.origem_id == 50)).one()


def test_contrato_apagado_na_receita_leva_as_despesas(origens, db):
    sincronizar()
    origens["cost_centers"] = []
    sincronizar()
    assert _contar(db, CdDespesa) == 0


def test_contrato_desativado_continua_com_as_despesas(origens, db):
    origens["cost_centers"][0]["active"] = False
    sincronizar()
    assert db.session.scalars(select(RcContrato)).one().ativo is False
    assert _contar(db, CdDespesa) == 2
