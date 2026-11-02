# 5.5 Signed execution context

Source: [architecture.md](../architecture.md)

```mermaid
sequenceDiagram
  autonumber
  participant API as API / RunManager
  participant G as LangGraph node
  participant TC as ToolClient
  participant LL as LiteLLM MCP gateway
  participant B as mcp-broker
  participant S as Domain service / MCP server
  participant DB as Postgres

  API->>API: Resolve principal, role, patient, clinic, consent
  API->>API: Mint signed _context (aud=mcp, TTL 120s, jti)
  G->>TC: Model chose tool + business args
  TC->>TC: Validate args against schema; reject patient_id
  TC->>TC: Inject _context and idempotency_key
  TC->>LL: POST /mcp-rest/tools/call (service key)
  LL->>LL: Check key/team tool permission
  LL->>B: Forward tool call
  B->>B: Verify signature, aud, exp, jti replay, allowlist
  B->>B: Re-check role, patient, clinic, consent, purpose
  B->>S: Forward with service token + request hash
  S->>DB: Scoped query/write + audit
  DB-->>S: Result
  S-->>B: Bounded JSON
  B-->>LL: Tool result
  LL-->>TC: Tool result
  TC-->>G: Validated typed result
```
