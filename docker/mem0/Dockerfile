# Self-hosted Mem0 API — local Ollama / llama-server only (no public OpenAI).
# Guide: https://mem0.ai/library/integrations/self-host-mem0-docker
FROM mem0/mem0-api-server:latest
USER root
RUN pip install --no-cache-dir "psycopg[binary,pool]" "mem0ai[graph]" rank-bm25 langchain-neo4j neo4j
COPY entrypoint.sh /entrypoint.sh
COPY config.json /app/config.json
RUN chmod +x /entrypoint.sh
WORKDIR /app
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
