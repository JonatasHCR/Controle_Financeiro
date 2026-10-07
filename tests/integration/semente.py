"""Massa de teste com números fáceis de conferir à mão.

4561: Receita e Controle, com itens e de-para.
4602: Receita e Controle, sem itens.
4660: só na Receita (custo zero).
4655: só no Controle (receita zero).

Período "todas" (base = mar/26): bruta 350.000; tributos 70.000; líquida
280.000; custo-alvo atual 243.478,26; custo 115.000; resultado 128.478,26.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from app.models import (
    CdCentro,
    CdDespesa,
    CdFornecedor,
    CdNatureza,
    CfgItem,
    CfgPendencia,
    CfgPleito,
    DeparaItem,
    RcAjuste,
    RcCliente,
    RcContrato,
    RcContratoCoordenador,
    RcNf,
    RcRecebimento,
)

NAT_A = "HONORÁRIOS PJ - ENGENHARIA"
NAT_B = "LOCAÇÃO DE VEÍCULOS"


def semear(session) -> None:
    session.add_all(
        [
            RcCliente(origem_id=1, nome="Companhia de Saneamento", nome_completo="Cia. Saneamento"),
            RcCliente(origem_id=2, nome="Prefeitura Municipal", nome_completo="Prefeitura"),
            RcContrato(
                origem_id=1,
                cr_code="4561",
                cr_norm="4561",
                descricao="Sistema adutor",
                numero_contrato="012/2024",
                cliente_origem_id=1,
                valor=D("1200000"),
                participacao=D("1"),
                data_inicio=date(2025, 1, 1),
                data_fim=date(2026, 12, 31),
            ),
            RcContrato(
                origem_id=2,
                cr_code="04602",
                cr_norm="4602",
                descricao="Drenagem",
                numero_contrato="118/2025",
                cliente_origem_id=2,
                valor=D("600000"),
                participacao=D("1"),
                data_inicio=date(2025, 6, 1),
                data_fim=date(2026, 6, 30),
            ),
            RcContrato(
                origem_id=3,
                cr_code="4660",
                cr_norm="4660",
                descricao="Orla",
                numero_contrato="077/2026",
                cliente_origem_id=2,
                valor=D("300000"),
                participacao=D("1"),
                data_inicio=date(2026, 7, 1),
                data_fim=date(2027, 6, 30),
            ),
            RcContratoCoordenador(
                contrato_origem_id=1, nome="Ana Ribeiro", nome_norm="ANA RIBEIRO"
            ),
            RcContratoCoordenador(
                contrato_origem_id=1, nome="Carlos Menezes", nome_norm="CARLOS MENEZES"
            ),
            RcContratoCoordenador(
                contrato_origem_id=2, nome="Carlos Menezes", nome_norm="CARLOS MENEZES"
            ),
            RcContratoCoordenador(
                contrato_origem_id=3, nome="Ana Ribeiro", nome_norm="ANA RIBEIRO"
            ),
            RcAjuste(
                origem_id=1,
                contrato_origem_id=1,
                tipo="valor",
                valor_anterior=D("1000000"),
                valor_novo=D("1200000"),
            ),
            RcNf(
                origem_id=1,
                contrato_origem_id=1,
                numero="701",
                emitida_em=date(2026, 1, 10),
                valor=D("100000"),
            ),
            RcNf(
                origem_id=2,
                contrato_origem_id=1,
                numero="702",
                emitida_em=date(2026, 2, 10),
                valor=D("100000"),
            ),
            RcNf(
                origem_id=3,
                contrato_origem_id=1,
                numero="703",
                emitida_em=date(2026, 3, 10),
                valor=D("100000"),
            ),
            RcNf(
                origem_id=4,
                contrato_origem_id=2,
                numero="801",
                emitida_em=date(2026, 2, 15),
                valor=D("50000"),
            ),
            RcRecebimento(
                origem_id=1, nf_origem_id=1, data_pagamento=date(2026, 2, 10), valor=D("100000")
            ),
            RcRecebimento(
                origem_id=2, nf_origem_id=2, data_pagamento=date(2026, 3, 10), valor=D("100000")
            ),
            RcRecebimento(
                origem_id=3, nf_origem_id=4, data_pagamento=date(2026, 3, 15), valor=D("50000")
            ),
            CdCentro(origem_id=10, codigo="4561", cr_norm="4561", nome="Sistema adutor"),
            CdCentro(origem_id=11, codigo="4602", cr_norm="4602", nome="Drenagem"),
            CdCentro(origem_id=12, codigo="4655", cr_norm="4655", nome="Proposta Metrô"),
            CdFornecedor(origem_id=1, nome="Fornecedor X"),
            CdNatureza(origem_id=1, nome=NAT_A, nome_norm="HONORARIOS PJ - ENGENHARIA"),
            CdNatureza(origem_id=2, nome=NAT_B, nome_norm="LOCACAO DE VEICULOS"),
        ]
    )
    despesas = [
        (10, 1, date(2026, 1, 15), "40000"),
        (10, 1, date(2026, 2, 15), "40000"),
        (10, 2, date(2026, 3, 15), "10000"),
        (11, 1, date(2026, 2, 20), "20000"),
        (12, 2, date(2026, 3, 5), "5000"),
    ]
    for i, (centro, natureza, data, valor) in enumerate(despesas, start=1):
        session.add(
            CdDespesa(
                origem_id=i,
                centro_origem_id=centro,
                fornecedor_origem_id=1,
                natureza_origem_id=natureza,
                data_baixa=data,
                valor_original=D(valor),
                valor_baixado=D(valor),
            )
        )
    session.add_all(
        [
            CfgItem(
                cr_norm="4561",
                codigo="1.1",
                descricao="Engenheiro fiscal (PJ)",
                unidade="Mensal",
                custo_alvo=D("500000"),
                ordem=0,
            ),
            CfgItem(
                cr_norm="4561",
                codigo="1.2",
                descricao="Veículo locado",
                unidade="Mensal",
                custo_alvo=D("100000"),
                ordem=1,
            ),
            DeparaItem(
                cr_norm="4561", natureza_nome_norm="HONORARIOS PJ - ENGENHARIA", item_codigo="1.1"
            ),
            DeparaItem(cr_norm="4561", natureza_nome_norm="LOCACAO DE VEICULOS", item_codigo="1.2"),
            CfgPendencia(
                cr_norm="4561",
                assunto="Renovar seguro-garantia",
                prazo=date(2026, 4, 1),
                prioridade="ALTA",
            ),
            CfgPendencia(
                cr_norm="4561", assunto="Já resolvida", prazo=date(2026, 1, 1), status="CONCLUÍDA"
            ),
            CfgPleito(
                cr_norm="4561",
                data_base=date(2025, 4, 1),
                descricao="Aditivo de valor",
                tipo="ADITIVO",
                status="VALIDADO",
                valor=D("200000"),
            ),
            CfgPleito(
                cr_norm="4561",
                data_base=date(2026, 3, 1),
                descricao="Reajuste",
                tipo="REAJUSTE",
                status="EM ANÁLISE",
                valor=D("50000"),
            ),
        ]
    )
    session.commit()
