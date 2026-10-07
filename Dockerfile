# Multi-estágio. O primeiro traduz o poetry.lock em requirements.txt; o segundo
# instala só isso. Assim o Poetry e o pip cache não viajam para a imagem final.

# --- estágio 1: resolver dependências ---------------------------------------
FROM python:3.12-slim AS dependencias

ENV PIP_NO_CACHE_DIR=1
ARG INSTALL_DEV=false

WORKDIR /app

RUN pip install --no-cache-dir "poetry==1.8.5" "poetry-plugin-export==1.8.0"

COPY pyproject.toml poetry.lock* ./
RUN if [ ! -f poetry.lock ]; then poetry lock --no-interaction --no-ansi; fi \
    && if [ "$INSTALL_DEV" = "true" ]; then \
           poetry export --with dev --without-hashes -f requirements.txt -o /tmp/req.txt; \
       else \
           poetry export --without-hashes -f requirements.txt -o /tmp/req.txt; \
       fi

# --- estágio 2: imagem de execução ------------------------------------------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Sao_Paulo

# postgresql-client: o pg_dump/pg_restore do painel admin roda dentro deste
# container, não num sidecar com socket Docker.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=dependencias /tmp/req.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt && rm /tmp/req.txt

# Chromium do Playwright para gerar o PDF do relatório. Caminho fixo e legível
# pelo usuário sem privilégio.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium && chmod -R o+rx /ms-playwright

# Usuário sem privilégio: se a aplicação for comprometida, o atacante não
# começa como root dentro do container. O uid é fixo para casar com o dono do
# bind mount de ./backups no host.
RUN groupadd --gid 10001 financeiro \
    && useradd --uid 10001 --gid financeiro --create-home --shell /usr/sbin/nologin financeiro

WORKDIR /app
COPY --chown=financeiro:financeiro . .

# sed: um checkout no Windows grava o .sh com CRLF, o shebang vira `/bin/sh\r`
# e o Docker reporta isso como se o entrypoint nao existisse.
RUN sed -i 's/\r$//' /app/entrypoint.sh \
    && chmod +x /app/entrypoint.sh \
    && mkdir -p /backups \
    && chown financeiro:financeiro /backups

USER financeiro

EXPOSE 8000
CMD ["/app/entrypoint.sh"]
