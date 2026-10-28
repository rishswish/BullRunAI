# One image, two entrypoints: the agent API (default) and the MCP server.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=8080
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bullrun_agent ./bullrun_agent
COPY evals ./evals
# Bake a prebuilt filings index into the image if one exists locally
# (otherwise set INDEX_GCS_URI and it is downloaded at startup).
COPY data ./data

RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Cloud Run injects $PORT. One worker per container; Cloud Run scales containers.
CMD ["sh", "-c", "uvicorn bullrun_agent.api:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
# MCP server: override the command with
#   python -m bullrun_agent.mcp_server --http
