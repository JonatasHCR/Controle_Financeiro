"""Cópia local do que vem da Receita (rc_) e do Controle de Despesa (cd_).

Só a sincronização escreve aqui. As relações usam o id de origem, e não FK
local: a ordem de chegada dos recursos não pode quebrar o upsert.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

DINHEIRO = Numeric(15, 2)


class _Espelho:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origem_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    origem_atualizado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Gerenciamento de Receita ------------------------------------------------


class RcCliente(_Espelho, db.Model):
    __tablename__ = "rc_clientes"

    nome: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    nome_completo: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")


class RcContrato(_Espelho, db.Model):
    """Centro de custo da Receita = contrato."""

    __tablename__ = "rc_contratos"

    cr_code: Mapped[str] = mapped_column(String(40), nullable=False)
    cr_norm: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    descricao: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    numero_contrato: Mapped[str | None] = mapped_column(String(100))
    coordenador: Mapped[str | None] = mapped_column(String(300))
    objeto: Mapped[str | None] = mapped_column(Text)
    cliente_origem_id: Mapped[int | None] = mapped_column(Integer, index=True)
    valor: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    participacao: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    data_inicio: Mapped[date | None] = mapped_column(Date)
    data_fim: Mapped[date | None] = mapped_column(Date)
    # Desativado na Receita: continua aqui, mas não recebe mais lançamento lá.
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class RcContratoCoordenador(db.Model):
    """Um nome por linha: na Receita os coordenadores vêm num texto com " / "."""

    __tablename__ = "rc_contrato_coordenadores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contrato_origem_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    nome_norm: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    __table_args__ = (UniqueConstraint("contrato_origem_id", "nome_norm"),)


class RcNf(_Espelho, db.Model):
    __tablename__ = "rc_nfs"

    contrato_origem_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    numero: Mapped[str] = mapped_column(String(40), nullable=False)
    cliente_nome: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    emitida_em: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # principal | reajuste
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, server_default="principal")
    valor: Mapped[Decimal] = mapped_column(DINHEIRO, nullable=False)
    observacoes: Mapped[str | None] = mapped_column(Text)


class RcRecebimento(_Espelho, db.Model):
    __tablename__ = "rc_recebimentos"

    nf_origem_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    data_pagamento: Mapped[date] = mapped_column(Date, nullable=False)
    valor: Mapped[Decimal] = mapped_column(DINHEIRO, nullable=False)


class RcAjuste(_Espelho, db.Model):
    """Aditivo de valor ou de prazo."""

    __tablename__ = "rc_ajustes"

    contrato_origem_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # valor | prazo
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)
    valor_anterior: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    valor_novo: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    data_anterior: Mapped[date | None] = mapped_column(Date)
    data_nova: Mapped[date | None] = mapped_column(Date)
    nota: Mapped[str | None] = mapped_column(Text)
    criado_origem_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RcPrevisao(_Espelho, db.Model):
    __tablename__ = "rc_previsoes"

    contrato_origem_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    competencia: Mapped[date | None] = mapped_column(Date)
    valor_previsto: Mapped[Decimal | None] = mapped_column(DINHEIRO)


# --- Controle de Despesa ------------------------------------------------------


class CdCentro(_Espelho, db.Model):
    __tablename__ = "cd_centros"

    codigo: Mapped[str] = mapped_column(String(40), nullable=False)
    cr_norm: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    nome: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")


class CdFornecedor(_Espelho, db.Model):
    __tablename__ = "cd_fornecedores"

    nome: Mapped[str] = mapped_column(String(200), nullable=False)


class CdNatureza(_Espelho, db.Model):
    __tablename__ = "cd_naturezas"

    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    nome_norm: Mapped[str] = mapped_column(String(200), nullable=False, index=True)


class CdDespesa(_Espelho, db.Model):
    __tablename__ = "cd_despesas"

    centro_origem_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fornecedor_origem_id: Mapped[int] = mapped_column(Integer, nullable=False)
    natureza_origem_id: Mapped[int] = mapped_column(Integer, nullable=False)
    data_baixa: Mapped[date] = mapped_column(Date, nullable=False)
    data_emissao: Mapped[date | None] = mapped_column(Date)
    valor_original: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    valor_baixado: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    referencia: Mapped[int | None] = mapped_column(Integer)
    documento: Mapped[str] = mapped_column(String(30), nullable=False, server_default="")
    historico: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    __table_args__ = (
        Index("ix_cd_despesas_centro_data", "centro_origem_id", "data_baixa"),
        Index(
            "ix_cd_despesas_centro_natureza_data",
            "centro_origem_id",
            "natureza_origem_id",
            "data_baixa",
        ),
    )
