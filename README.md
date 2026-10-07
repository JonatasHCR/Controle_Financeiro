# Controle Financeiro

Sexto sistema da plataforma UFC Engenharia: painel financeiro por contrato (CR) e
relatório em PDF. **Só visualiza** — contratos, NFs, recebimentos e aditivos vêm do
Gerenciamento de Receita; o custo realizado vem do Controle de Despesa. Aqui se
cadastram apenas os complementos que as origens não têm (custo-alvo dos itens, fim
da execução, de-para natureza → item, BMs, pendências e pleitos).

| | |
|---|---|
| Porta | `3060` (`CONTROLE_FINANCEIRO_PORT`) |
| Login | Keycloak, client `controle-financeiro-web`, grupo `/apps/controle-financeiro` |
| Perfis | leitor (painel e PDF) · operador (+ Configuração) · admin (+ Administração e Auditoria) |
| Stack | Flask 3, Jinja2, Chart.js, SQLAlchemy 2, Postgres 17, Playwright (PDF) |

## Subir

```sh
cp .env.exemplo .env          # preencha; os campos [infra] vêm do infra/scripts/sync_host_ip.py
docker compose up -d --build  # dev (override com flask run e db-test)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build   # produção
```

O `stack.ps1` da raiz sobe o controle financeiro por último, depois da receita e do controle.

Serviços: `db`, `web` (gunicorn), `sync` (laço de sincronização a cada
`SYNC_INTERVAL_MINUTES`), `backup` (pg_dump a cada `BACKUP_INTERVAL_HOURS`, mantém
`BACKUP_KEEP`; prefixo `controle_financeiro_auto_`). Backup manual pelo painel admin sai com
`controle_financeiro_manual_` e não entra na rotação.

## Sincronização

```sh
docker compose exec web flask sincronizar              # incremental (com recarga completa 1x/dia)
docker compose exec web flask sincronizar --completo   # força recarga completa
```

Lê `RECEITA_API_URL`/`RECEITA_API_TOKEN` e `CONTROLE_API_URL`/`CONTROLE_API_TOKEN`.
Os CRs analisados são a **união** das duas origens (chave: código do CR sem zeros à
esquerda). CR só na Receita entra com custo zero; CR só no Controle entra com
receita zero.

## Testes

```sh
docker compose up -d db-test
docker compose run --rm --no-deps -e APP_CONFIG=test web pytest
```

## Onde está o quê

- `app/analise/` — período, filtros e o cálculo do painel (`montar_painel`), usado pela tela, pelo JSON e pelo PDF.
- `app/sync/` — clientes das APIs, upsert, exclusões, reconciliação e a trava.
- `app/configuracao/` — telas de complementos e a planilha modelo (gerar e importar com prévia).
- `app/relatorio/` — PDF: o Chromium abre `/relatorio/impressao` com um token assinado de 2 minutos.
- `app/static/js/painel.js` — desenho dos gráficos (Chart.js) a partir do JSON.
