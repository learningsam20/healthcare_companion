#!/usr/bin/env bash
# Boot Mem0 against LiteLLM (OpenAI-compatible). LiteLLM routes to Ollama / llama-server.
set -euo pipefail

LITELLM_URL="${OPENAI_BASE_URL:-${LLM_BASE_URL:-http://litellm:4000/v1}}"
LLM_PROVIDER="${LLM_PROVIDER:-openai}"
LLM_MODEL="${LLM_MODEL:-qwen2.5:3b-instruct-q4_K_M}"
EMBEDDER_PROVIDER="${EMBEDDER_PROVIDER:-openai}"
EMBEDDER_MODEL="${EMBEDDER_MODEL:-bge-m3}"
PG_PASS="${POSTGRES_PASSWORD:-mem0}"
NEO_PASS="${NEO4J_PASSWORD:-mem0graph}"
API_KEY="${OPENAI_API_KEY:-sk-local}"

export OPENAI_API_KEY="${API_KEY}"
export OPENAI_BASE_URL="${LITELLM_URL}"
export OPENAI_API_BASE="${LITELLM_URL}"

cat > /tmp/mem0-config.json <<EOF
{
  "llm": {
    "provider": "${LLM_PROVIDER}",
    "config": {
      "model": "${LLM_MODEL}",
      "temperature": 0.1,
      "max_tokens": 2000,
      "api_key": "${API_KEY}",
      "openai_base_url": "${LITELLM_URL}"
    }
  },
  "embedder": {
    "provider": "${EMBEDDER_PROVIDER}",
    "config": {
      "model": "${EMBEDDER_MODEL}",
      "api_key": "${API_KEY}",
      "openai_base_url": "${LITELLM_URL}"
    }
  },
  "vector_store": {
    "provider": "pgvector",
    "config": {
      "host": "${POSTGRES_HOST:-mem0-postgres}",
      "port": ${POSTGRES_PORT:-5432},
      "user": "${POSTGRES_USER:-mem0}",
      "password": "${PG_PASS}",
      "dbname": "${POSTGRES_DB:-mem0}",
      "embedding_model_dims": ${MEM0_EMBED_DIMS:-1024}
    }
  },
  "graph_store": {
    "provider": "neo4j",
    "config": {
      "url": "${NEO4J_URI:-bolt://mem0-neo4j:7687}",
      "username": "${NEO4J_USERNAME:-neo4j}",
      "password": "${NEO_PASS}"
    }
  }
}
EOF
export MEM0_CONFIG_PATH=/tmp/mem0-config.json

echo "Mem0 inference via LiteLLM: ${LITELLM_URL} llm=${LLM_MODEL} embed=${EMBEDDER_MODEL}"
exec "$@"
