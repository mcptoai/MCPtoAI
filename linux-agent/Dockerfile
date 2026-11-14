# MCPtoAI for Linux — konteyner imajı.
# 1. aşama: paket wheel olarak derlenir; son imaja kaynak kod ve derleme araçları girmez.
FROM python:3.12-slim AS build
WORKDIR /src
COPY linux-agent/pyproject.toml linux-agent/setup.py linux-agent/README.md ./
COPY linux-agent/mcptoai_linux ./mcptoai_linux
COPY shared-core/mcptoai_core /shared-core/mcptoai_core
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/mcptoai/MCPtoAI"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCPTOAI_CONTAINER=1 \
    XDG_CONFIG_HOME=/data
# git: proje komutları ve GitHub için; ca-certificates: TLS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels mcptoai && rm -rf /wheels
# Root olmayan kullanıcı. Kasa ve ayarlar birim olarak bağlanan .config içinde tutulur;
# klasör imajda 0700 olarak oluşturulur ki yeni birim bu sahipliği ve izni devralsın.
RUN useradd --create-home --uid 1000 mcptoai \
 && install -d -m 0700 -o mcptoai -g mcptoai /data
USER mcptoai
WORKDIR /home/mcptoai
ENTRYPOINT ["python", "-m", "mcptoai_linux.container_entrypoint"]
CMD ["connect"]
