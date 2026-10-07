"""O que a sincronização não traz e só o Controle Financeiro usa.

Tudo pendurado no cr_norm, nunca em id de origem: sobrevive a uma restauração
da Receita ou do Controle. Nenhuma tabela aqui cria contrato, NF ou despesa.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

DINHEIRO = Numeric(15, 2)

PRIORIDADES = ("ALTA", "MÉDIA", "BAIXA")
STATUS_PENDENCIA = ("ABERTA", "CONCLUÍDA")
TIPOS_PLEITO = ("ADITIVO", "REAJUSTE", "REEQUILÍBRIO")
STATUS_PLEITO = ("VALIDADO", "FEITO", "EM ANÁLISE", "SOLICITAR")
# validado e feito contam como aprovados
STATUS_APROVADOS = ("VALIDADO", "FEITO")


class _Rastro:
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    atualizado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("tb_usuarios.id", ondelete="SET NULL")
    )


class CfgContrato(_Rastro, db.Model):
    """A única data que a Receita não tem: o fim da execução."""

    __tablename__ = "cfg_contratos"

    cr_norm: Mapped[str] = mapped_column(String(40), primary_key=True)
    fim_execucao: Mapped[date | None] = mapped_column(Date)


class CfgItem(_Rastro, db.Model):
    __tablename__ = "cfg_itens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cr_norm: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    codigo: Mapped[str] = mapped_column(String(20), nullable=False)
    descricao: Mapped[str] = mapped_column(String(300), nullable=False)
    unidade: Mapped[str] = mapped_column(String(20), nullable=False, server_default="")
    quantidade: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    custo_alvo: Mapped[Decimal] = mapped_column(DINHEIRO, nullable=False, server_default="0")
    # Vazio = igual ao custo-alvo.
    custo_alvo_projetado: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    quantidade_medida: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    ordem: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        UniqueConstraint("cr_norm", "codigo"),
        CheckConstraint("custo_alvo >= 0", name="ck_item_custo_alvo"),
    )


class DeparaItem(_Rastro, db.Model):
    """Natureza do Controle de Despesa → item do contrato."""

    __tablename__ = "cfg_depara"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cr_norm: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    natureza_nome_norm: Mapped[str] = mapped_column(String(200), nullable=False)
    # Vazio = não classificado (decidido de propósito).
    item_codigo: Mapped[str] = mapped_column(String(20), nullable=False, server_default="")

    __table_args__ = (UniqueConstraint("cr_norm", "natureza_nome_norm"),)


class CfgBm(_Rastro, db.Model):
    """Número do boletim de medição de cada NF da Receita."""

    __tablename__ = "cfg_bms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nf_origem_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    cr_norm: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    # Primeiro dia do mês da data-base.
    data_base: Mapped[date | None] = mapped_column(Date)


class CfgPendencia(_Rastro, db.Model):
    __tablename__ = "cfg_pendencias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cr_norm: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    assunto: Mapped[str] = mapped_column(Text, nullable=False)
    prazo: Mapped[date | None] = mapped_column(Date)
    prioridade: Mapped[str] = mapped_column(String(10), nullable=False, server_default="MÉDIA")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="ABERTA")


class CfgPleito(_Rastro, db.Model):
    """Aditivo, reajuste ou reequilíbrio em qualquer fase (solicitado a feito)."""

    __tablename__ = "cfg_pleitos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cr_norm: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    data_base: Mapped[date | None] = mapped_column(Date)
    descricao: Mapped[str] = mapped_column(Text, nullable=False)
    tipo: Mapped[str] = mapped_column(String(15), nullable=False, server_default="ADITIVO")
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="SOLICITAR")
    valor: Mapped[Decimal] = mapped_column(DINHEIRO, nullable=False, server_default="0")
    observacao: Mapped[str | None] = mapped_column(Text)


class Parametros(_Rastro, db.Model):
    """Tributos e taxa adm. '*' é o padrão global; um CR sobrescreve."""

    __tablename__ = "cfg_parametros"

    cr_norm: Mapped[str] = mapped_column(String(40), primary_key=True)
    tributos: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    taxa_adm: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)


class ConfigImportacao(db.Model):
    __tablename__ = "cfg_importacoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    arquivo: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("tb_usuarios.id", ondelete="SET NULL")
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    contagens: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    avisos: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")


# --- sincronização -------------------------------------------------------------


class SyncMarca(db.Model):
    __tablename__ = "sync_marcas"

    fonte: Mapped[str] = mapped_column(String(20), primary_key=True)
    recurso: Mapped[str] = mapped_column(String(40), primary_key=True)
    marca_dados: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marca_exclusoes: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultima_completa_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncExecucao(db.Model):
    __tablename__ = "sync_execucoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # automatico | manual | noturno
    disparo: Mapped[str] = mapped_column(String(15), nullable=False)
    iniciado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    terminado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ok | erro | parcial | em_andamento
    status: Mapped[str] = mapped_column(String(15), nullable=False, server_default="em_andamento")
    contagens: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    erro: Mapped[str | None] = mapped_column(Text)
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("tb_usuarios.id", ondelete="SET NULL")
    )
