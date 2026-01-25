ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1

RUN apk add --no-cache \
    python3 py3-pip \
    nodejs npm \
    ca-certificates bash

# Virtualenv (PEP668 miatt)
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel

# Python MCP stack
RUN /opt/venv/bin/pip install --no-cache-dir \
    "mcp==1.26.0" \
    "mcp-proxy==0.11.0"

# Node mcp-remote
RUN npm install -g mcp-remote@0.1.37

# Rootfs bemásolása (ebben lesz /app/mcp_schema_shim.py is)
COPY rootfs/ /

RUN chmod a+x /etc/services.d/kifli-mcp/run \
 && chmod a+x /app/mcp_schema_shim.py
