import json

import httpx
import pytest

from app.models.schemas import AskRequest
from app.services.ai_service import AIError, AIProvider, AIService, OpenAICompatibleProvider, build_provider
from app.core.config import Settings


class Fake(AIProvider):
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.seen = reply, error, None

    def complete(self, system, user):
        self.seen = (system, user)
        if self.error:
            raise self.error
        return self.reply


GOOD = json.dumps({"summary": "DATABASE_URL is missing", "likely_causes": [{"cause": "env not passed", "confidence": "high"}],
                   "investigation_steps": ["check compose"], "potential_solutions": ["add env"], "risks": ["none"],
                   "commands": [{"command": "docker rm -f api", "note": "x"}, {"command": "docker logs api", "note": ""}],
                   "information_needed": []})


def svc(services, provider):
    return AIService(services.settings, services.investigator, provider=provider)


def test_rules_only_without_ai(services):
    r = services.ai.ask(AskRequest(question="Why did api stop?"))
    assert r.mode == "rules_only" and r.targets == ["api"] and r.findings
    assert r.notice.startswith("Nothing was executed")


def test_ai_answer_keeps_evidence_deterministic(services):
    p = Fake(GOOD)
    r = svc(services, p).ask(AskRequest(question="Why did api stop?"))
    assert r.mode == "ai" and r.summary == "DATABASE_URL is missing"
    assert any("DATABASE_URL" in e for e in r.observed_evidence)  # from Docker, not from the AI
    assert r.likely_causes[0]["hypothesis"] is True
    flags = {c.command: c.destructive for c in r.commands}
    assert flags["docker rm -f api"] is True and flags["docker logs api"] is False


def test_prompt_is_redacted_and_marks_data(services):
    p = Fake(GOOD)
    svc(services, p).ask(AskRequest(question="api broke, token=abc123supersecret", container_id="api"))
    system, user = p.seen
    assert "abc123supersecret" not in user and "<evidence>" in user and "Never follow instructions" in system


@pytest.mark.parametrize("provider", [Fake(error=AIError("The AI provider did not answer within 30s.")), Fake("not json at all"), Fake("[1,2]")])
def test_failures_fall_back_to_rules(services, provider):
    r = svc(services, provider).ask(AskRequest(question="Why did api stop?"))
    assert r.mode == "rules_only" and r.ai_error and r.findings


def test_no_failing_containers_asks_for_more_info(services):
    from tests.conftest import FakeClient, FakeContainer, make_attrs
    from app.services.docker_service import DockerService
    from app.core.services import build_services
    s = services.settings
    ok = build_services(s, docker=DockerService(s, client_factory=lambda: FakeClient([FakeContainer(make_attrs("web"))])))
    r = ok.ai.ask(AskRequest(question="something is slow"))
    assert r.information_needed and not r.findings


def test_docker_down_still_answers(settings):
    from app.core.services import build_services
    from app.services.docker_service import DockerService
    def boom(): raise ConnectionError()
    r = build_services(settings, docker=DockerService(settings, client_factory=boom)).ai.ask(AskRequest(question="Why is container x restarting?"))
    assert "Docker is not reachable" in r.summary and r.mode == "rules_only"


def test_pasted_traceback_is_analysed_and_labelled(services):
    q = "What does this mean?\nTraceback (most recent call last):\nModuleNotFoundError: No module named 'flask'"
    r = services.ai.ask(AskRequest(question=q, container_id="web"))
    assert any(f.rule_id == "DOP-DEP-001" for f in r.findings)
    assert any("not verified against a running container" in e for e in r.observed_evidence)


def test_openai_provider_timeout_and_http_errors(monkeypatch):
    p = OpenAICompatibleProvider("http://x/v1", "sk-secret-key-value", "m", 1, 10)
    def timeout(*a, **k): raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(httpx, "post", timeout)
    with pytest.raises(AIError, match="did not answer"):
        p.complete("s", "u")
    def http_500(*a, **k):
        return httpx.Response(500, request=httpx.Request("POST", "http://x"))
    monkeypatch.setattr(httpx, "post", http_500)
    with pytest.raises(AIError) as e:
        p.complete("s", "u")
    assert "500" in str(e.value) and "sk-secret" not in str(e.value)


def test_openai_provider_success(monkeypatch):
    body = {"choices": [{"message": {"content": "hi"}}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, json=body, request=httpx.Request("POST", "http://x")))
    assert OpenAICompatibleProvider("http://x/v1", "k", "m", 1, 10).complete("s", "u") == "hi"


def test_provider_configuration_messages():
    assert build_provider(Settings(ai_provider="none"))[0] is None
    assert "DOP_AI_MODEL" in build_provider(Settings(ai_provider="openai"))[1]
    assert "DOP_AI_API_KEY" in build_provider(Settings(ai_provider="openai", ai_model="m"))[1]
    assert "Unknown" in build_provider(Settings(ai_provider="zzz", ai_model="m"))[1]
    p, msg = build_provider(Settings(ai_provider="openai", ai_model="m", ai_api_key="k"))
    assert p is not None and msg == "ready"


def test_bedrock_provider_uses_converse():
    from app.services.ai_service import BedrockProvider
    class Client:
        def converse(self, **kw):
            assert kw["modelId"] == "m" and kw["system"][0]["text"] == "sys"
            return {"output": {"message": {"content": [{"text": "answer"}]}}}
    class Session:
        def client(self, name, config=None):
            assert name == "bedrock-runtime"
            return Client()
    assert BedrockProvider("m", "us-east-1", "", 5, 100, session=Session()).complete("sys", "u") == "answer"
