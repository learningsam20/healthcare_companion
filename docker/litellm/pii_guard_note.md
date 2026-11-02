# LiteLLM proxy de-identification

Defence-in-depth: product egress is enforced in `LlmGateway` (composite PII gate).
LiteLLM itself does not de-identify. Do not point browser or partner traffic at
LiteLLM bypassing the API. When adding a proxy callback, it must call mcp-pii
`/tools/redact` and refuse if `engine != composite`.
