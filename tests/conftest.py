"""Offline tests never inherit the operator's live evaluation configuration."""
import pytest


@pytest.fixture(autouse=True)
def isolate_live_configuration(monkeypatch):
    for name in ('RT_BUDGET_PROFILE','HYDROGEN_EVALUATION_LIMIT','HYDROGEN_JUDGING_LIMIT',
                 'RT_MODEL_DAILY_LIMITS','RT_MODEL_PROJECT_LIMITS','RT_EVIDENCE_CRITIC','RT_AGENT_PLANNING',
                 'RT_DECISION_ENABLED','RT_EVIDENCE_REVIEW_PROVIDER','RT_DECISION_WORKFLOW_LIMIT','RT_FUTURE_FULLTEXT',
                 'RT_PUBLIC_DNS_RESOLVER','RT_EMBED_PROVIDER','RT_RETRIEVAL_BASE',
                 'GEMINI_API_KEY','GEMINI_API_KEY2'):
        monkeypatch.delenv(name,raising=False)
