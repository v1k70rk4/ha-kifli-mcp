# A Supervisor a BUILD_ARCH-ot mindig átadja (amd64 / aarch64), a BUILD_FROM-ot
# viszont build.yaml nélkül nem – ezért az alapképet az architektúrából képezzük,
# különben aarch64-en (pl. HA Green) az amd64 kép miatt elbukik a build.
ARG BUILD_ARCH=amd64
ARG BUILD_FROM=ghcr.io/home-assistant/${BUILD_ARCH}-base:latest
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1

RUN apk add --no-cache \
    python3 py3-pip \
    ca-certificates bash

# Virtualenv (PEP668 miatt)
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel

# Python MCP stack. 2.0 óta nincs Node / mcp-remote: az upstream OAuth-ot az
# mcp SDK beépített kliense intézi, az ingress oldalt a starlette/uvicorn adja
# (mindkettő az mcp csomag függősége).
RUN /opt/venv/bin/pip install --no-cache-dir \
    "mcp==1.26.0" \
    "mcp-proxy==0.11.0" \
    "python-multipart>=0.0.9"

# Rootfs bemásolása (ebben lesz /app/mcp_schema_shim.py és /app/kifli_auth.py is)
COPY rootfs/ /

RUN chmod a+x /etc/services.d/kifli-mcp/run \
 && chmod a+x /app/mcp_schema_shim.py
