"""Offline tests never inherit the operator's live evaluation configuration."""
import pytest


@pytest.fixture(autouse=True)
def isolate_live_configuration(monkeypatch):
    for name in ('RT_BUDGET_PROFILE','HYDROGEN_EVALUATION_LIMIT','HYDROGEN_JUDGING_LIMIT',
                 'RT_MODEL_DAILY_LIMITS','RT_MODEL_PROJECT_LIMITS','RT_EVIDENCE_CRITIC','RT_AGENT_PLANNING',
                 'RT_DECISION_ENABLED','RT_EVIDENCE_REVIEW_PROVIDER','RT_DECISION_REVIEW_FALLBACK','RT_DECISION_WORKFLOW_LIMIT','RT_FUTURE_FULLTEXT',
                 'RT_PUBLIC_DNS_RESOLVER','RT_EMBED_PROVIDER','RT_RETRIEVAL_BASE',
                 'GEMINI_API_KEY','GEMINI_API_KEY2','GEMINI_PROXY','RT_CA_BUNDLE',
                 'RT_MODEL_DEEP','RT_MODEL_ANSWER','RT_MODEL_LIGHT','RT_MODEL_VERIFY',
                 'RT_WORKFLOW_MODEL_CALLS','RT_WORKSPACE_DAILY_CALLS'):
        monkeypatch.delenv(name,raising=False)
    for name in ('RT_PREFERRED_CREDENTIAL','RT_LEGACY_PROJECT_MAP','RT_ENABLE_RERANK','RT_RETRIEVAL_QUERY_TIMEOUT','RT_PROVIDER_MODE'):
        monkeypatch.delenv(name,raising=False)
    # Document cards stay offline in tests: no live arXiv/Crossref lookups, no model calls.
    monkeypatch.setenv('RT_CARD_NETWORK','false')
    monkeypatch.setenv('RT_CARD_MODEL','false')
    # Query rewriting is one extra light call; fixture providers do not expect it.
    monkeypatch.setenv('RT_QUERY_REWRITE','false')
