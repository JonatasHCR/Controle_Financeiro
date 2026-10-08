"""Filtros da tela e regra de período.

Modos: todas | acum (até o mês) | mes (só o mês) | intervalo (de data a data).
No intervalo, NF entra pela emissão e despesa pela data de baixa; nos demais,
vale o mês (data-base da NF, mês da baixa da despesa).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

MODOS = ("todas", "acum", "mes", "intervalo")
# Resumo agrupado por contratante, coordenador ou centro de custo.
AGRUPAMENTOS = ("cli", "coord", "cr")
MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def ym(d: date | None) -> str | None:
    return f"{d.year:04d}-{d.month:02d}" if d else None


def add_meses(mes: str, n: int) -> str:
    ano, m = map(int, mes.split("-"))
    total = ano * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def meses_entre(a: str, b: str) -> int:
    ya, ma = map(int, a.split("-"))
    yb, mb = map(int, b.split("-"))
    return (yb - ya) * 12 + (mb - ma)


def fim_do_mes(mes: str) -> date:
    proximo = add_meses(mes, 1)
    ano, m = map(int, proximo.split("-"))
    return date.fromordinal(date(ano, m, 1).toordinal() - 1)


def rotulo_mes(mes: str) -> str:
    ano, m = mes.split("-")
    return f"{MESES[int(m) - 1]}/{ano[2:]}"


def data_br(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def _mes_valido(valor: str | None) -> str | None:
    try:
        ano, m = (valor or "").split("-")[:2]
        if 1 <= int(m) <= 12 and len(ano) == 4:
            return f"{int(ano):04d}-{int(m):02d}"
    except ValueError:
        pass
    return None


def _data_valida(valor: str | None) -> date | None:
    try:
        return date.fromisoformat(valor or "")
    except ValueError:
        return None


@dataclass
class Filtro:
    clientes: list[str] = field(default_factory=list)
    coordenadores: list[str] = field(default_factory=list)
    crs: list[str] = field(default_factory=list)
    modo: str = "todas"
    mes: str | None = None
    de: date | None = None
    ate: date | None = None
    # "open" = só NFs não pagas
    nf: str = "all"
    agrupar: str = "cli"

    @classmethod
    def da_query(cls, args) -> Filtro:
        lista = lambda chave: [v for v in args.getlist(chave) if v]  # noqa: E731
        modo = args.get("modo", "todas")
        filtro = cls(
            clientes=lista("cliente"),
            coordenadores=lista("coordenador"),
            crs=lista("cr"),
            modo=modo if modo in MODOS else "todas",
            mes=_mes_valido(args.get("mes")),
            de=_data_valida(args.get("de")),
            ate=_data_valida(args.get("ate")),
            nf="open" if args.get("nf") == "open" else "all",
            agrupar=args.get("agrupar") if args.get("agrupar") in AGRUPAMENTOS else "cli",
        )
        # a data inicial nunca passa da final (o servidor confere de novo)
        if filtro.de and filtro.ate and filtro.de > filtro.ate:
            filtro.de, filtro.ate = filtro.ate, filtro.de
        return filtro


@dataclass
class Periodo:
    """O filtro de período resolvido contra os dados existentes."""

    modo: str
    base_max: str
    mes: str | None = None
    de: date | None = None
    ate: date | None = None

    @classmethod
    def resolver(
        cls, filtro: Filtro, base_max: str, data_min: date | None, data_max: date | None
    ) -> Periodo:
        modo = filtro.modo
        if modo in ("acum", "mes"):
            # sem mês escolhido, vai para o mais recente da base
            return cls(modo, base_max, mes=filtro.mes or base_max)
        if modo == "intervalo":
            ate = filtro.ate or data_max or fim_do_mes(base_max)
            de = filtro.de or date.fromisoformat(add_meses(ym(ate), -11) + "-01")
            if data_min and de < data_min:
                de = data_min
            if de > ate:
                de = ate
            return cls(modo, base_max, de=de, ate=ate)
        return cls("todas", base_max)

    @property
    def corte(self) -> str:
        if self.modo == "todas":
            return self.base_max
        if self.modo == "intervalo":
            return min(ym(self.ate), self.base_max)
        return self.mes

    def mes_no_periodo(self, mes: str) -> bool:
        if self.modo == "todas":
            return mes <= self.base_max
        if self.modo == "mes":
            return mes == self.mes
        if self.modo == "acum":
            return mes <= self.mes
        return ym(self.de) <= mes <= ym(self.ate)

    def nf_no_periodo(self, competencia: str, emitida_em: date) -> bool:
        if self.modo == "intervalo":
            return self.de <= emitida_em <= self.ate
        return self.mes_no_periodo(competencia)

    def despesa_no_periodo(self, data_baixa: date) -> bool:
        if self.modo == "intervalo":
            return self.de <= data_baixa <= self.ate
        return self.mes_no_periodo(ym(data_baixa))

    @property
    def texto(self) -> str:
        if self.modo == "mes":
            return "somente " + rotulo_mes(self.mes)
        if self.modo == "acum":
            return "acumulado até " + rotulo_mes(self.mes)
        if self.modo == "intervalo":
            return f"de {data_br(self.de)} a {data_br(self.ate)}"
        return f"todas as datas-base (até {rotulo_mes(self.base_max)})"
