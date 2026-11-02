FROM sahyog-api:local
USER root
COPY main.py /app/services/mcp-pii/sahyog_mcp_pii/main.py
RUN chown sahyog:sahyog /app/services/mcp-pii/sahyog_mcp_pii/main.py
USER sahyog
ENTRYPOINT []
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "apps/api"]
