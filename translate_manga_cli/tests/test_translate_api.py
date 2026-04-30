from tests.test_constants import TEST_BASE_URL


def test_translate_route_uses_openai_compatible_client(client, monkeypatch):
    captured = {"messages": None}

    class FakeCompletions:
        def create(self, model, messages, stream, timeout=None, temperature=None):
            captured["model"] = model
            captured["messages"] = messages
            captured["stream"] = stream
            captured["timeout"] = timeout
            captured["temperature"] = temperature

            message = type("Message", (), {"content": "<|1|>你好\n<|2|>世界"})()
            choice = type("Choice", (), {"message": message})()
            return type("Completion", (), {"choices": [choice]})()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = FakeChat()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    response = client.post(
        "/api/pipeline/translate",
        json={
            "texts": ["こんにちは", "世界"],
            "model": "mimo-v2.5-pro",
            "baseUrl": TEST_BASE_URL,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["translatedTexts"] == ["你好", "世界"]
    assert captured["model"] == "mimo-v2.5-pro"
    assert captured["base_url"] == TEST_BASE_URL
    assert captured["stream"] is False
    assert captured["timeout"] == 90.0
    assert captured["temperature"] == 0
    assert captured["messages"][0]["content"].startswith("你是专业漫画翻译器")
    assert "<|1|>こんにちは" in captured["messages"][1]["content"]
    assert "<|2|>世界" in captured["messages"][1]["content"]


def test_translate_route_uses_env_defaults_when_request_omits_api_fields(monkeypatch, tmp_path):
    from src.app import create_app

    monkeypatch.setenv("TRANSLATE_MANGA_CLI_MODEL", "env-model")
    monkeypatch.setenv("TRANSLATE_MANGA_CLI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("TRANSLATE_MANGA_CLI_API_KEY", "env-key")

    app = create_app({"TESTING": True, "DATA_ROOT": str(tmp_path / "data")})
    client = app.test_client()
    captured = {}

    def fake_translate_texts(self, texts, model, base_url, api_key="dummy", context_snapshot=None):
        captured["texts"] = texts
        captured["model"] = model
        captured["base_url"] = base_url
        captured["api_key"] = api_key
        return ["你好"]

    monkeypatch.setattr(
        "src.app.routes.pipeline.OpenAICompatibleTranslator.translate_texts",
        fake_translate_texts,
    )

    response = client.post(
        "/api/pipeline/translate",
        json={
            "texts": ["こんにちは"],
        },
    )

    assert response.status_code == 200
    assert response.get_json()["translatedTexts"] == ["你好"]
    assert captured["model"] == "env-model"
    assert captured["base_url"] == "https://env.example/v1"
    assert captured["api_key"] == "env-key"
