"""Agent runtime: distinct LangGraph agents + shared model/MCP clients.

Catalogue (ingest stays a worker, not an agent):
- intent — emergency scan + intent classification
- w1_triage — specialty match + scheduling shortlist
- w2_ask — retrieve / answer / citation validate
- conversation — general / clarify replies
- w3_scribe — clinical note draft (existing)
- x01_nursing — bounded summary via w2_ask when feature flag is on
"""
