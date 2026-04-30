import httpx
import openai

from tests.test_constants import TEST_BASE_URL
from src.core.translate.openai_compatible import (
    OpenAICompatibleTranslator,
    SABER_BATCH_SYSTEM_TEMPLATE,
    _build_batch_messages,
    _parse_numbered_translations,
)


def test_translate_texts_preserves_empty_slots(monkeypatch):
    class FakeCompletions:
        def create(self, model, messages, stream, timeout=None, temperature=None):
            message = type("Message", (), {"content": "<|1|>你好"})()
            choice = type("Choice", (), {"message": message})()
            return type("Completion", (), {"choices": [choice]})()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.chat = FakeChat()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    result = OpenAICompatibleTranslator().translate_texts(
        texts=["", "こんにちは", "   "],
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
    )

    assert result == ["", "你好", ""]


def test_translate_texts_includes_context_snapshot(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, model, messages, stream, timeout=None, temperature=None):
            captured["messages"] = messages
            message = type("Message", (), {"content": "<|1|>学姐"})()
            choice = type("Choice", (), {"message": message})()
            return type("Completion", (), {"choices": [choice]})()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.chat = FakeChat()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    result = OpenAICompatibleTranslator().translate_texts(
        texts=["先輩"],
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        context_snapshot={
            "mangaContext": "这是一部成年人黑色幽默短篇漫画, 语气克制。",
            "confirmedTranslations": ["学姐"],
            "glossary": {"先輩": "学姐"},
        },
    )

    assert result == ["学姐"]
    assert "漫画背景" in captured["messages"][-1]["content"]
    assert "成年人黑色幽默短篇漫画" in captured["messages"][-1]["content"]
    assert "邻近页确认译文" in captured["messages"][-1]["content"]
    assert "先輩 -> 学姐" in captured["messages"][-1]["content"]


def test_system_prompt_requests_compact_punctuation():
    assert "半角标点" in SABER_BATCH_SYSTEM_TEMPLATE
    assert "尽量少用中文全角标点" in SABER_BATCH_SYSTEM_TEMPLATE


def test_build_batch_messages_uses_compact_two_message_layout():
    messages = _build_batch_messages(["こんにちは"])

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "<|1|>こんにちは" in messages[1]["content"]


def test_parse_numbered_translations_compacts_punctuation():
    result = _parse_numbered_translations("<|1|>会有一个白色的夜晚，真的！？……", 1)

    assert result == ["会有一个白色的夜晚,真的!?…"]


def test_translate_texts_passes_request_timeout(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, model, messages, stream, timeout=None, temperature=None):
            captured["timeout"] = timeout
            captured["temperature"] = temperature
            message = type("Message", (), {"content": "<|1|>你好"})()
            choice = type("Choice", (), {"message": message})()
            return type("Completion", (), {"choices": [choice]})()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.chat = FakeChat()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    result = OpenAICompatibleTranslator().translate_texts(
        texts=["こんにちは"],
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
    )

    assert result == ["你好"]
    assert captured["timeout"] == 90.0
    assert captured["temperature"] == 0


def test_translate_texts_falls_back_to_curl_on_api_connection_error(monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, model, messages, stream, timeout=None, temperature=None):
            raise openai.APIConnectionError(
                message="Connection error.",
                request=httpx.Request("POST", f"{TEST_BASE_URL}/chat/completions"),
            )

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.chat = FakeChat()

    class FakeCompletedProcess:
        def __init__(self):
            self.stdout = '{"choices":[{"message":{"content":"<|1|>你好"}}]}'
            self.stderr = ""
            self.returncode = 0

    def fake_run(args, capture_output, text, encoding, errors, timeout, check):
        captured["args"] = args
        captured["timeout"] = timeout
        return FakeCompletedProcess()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setattr("subprocess.run", fake_run)

    result = OpenAICompatibleTranslator().translate_texts(
        texts=["こんにちは"],
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
    )

    assert result == ["你好"]
    assert captured["args"][0].lower().endswith("curl.exe")


def test_translate_texts_with_metadata_runs_three_rounds_and_collects_usage(monkeypatch):
    captured = {"messages": []}

    responses = [
        ("<|1|>你好", type("Usage", (), {"prompt_tokens": 120, "completion_tokens": 20, "total_tokens": 140})()),
        ("<|1|>你好呀", type("Usage", (), {"prompt_tokens": 180, "completion_tokens": 24, "total_tokens": 204})()),
        ("<|1|>你好呀", type("Usage", (), {"prompt_tokens": 90, "completion_tokens": 12, "total_tokens": 102})()),
    ]

    class FakeCompletions:
        def create(self, model, messages, stream, timeout=None, temperature=None):
            captured["messages"].append(messages)
            content, usage = responses.pop(0)
            message = type("Message", (), {"content": content})()
            choice = type("Choice", (), {"message": message})()
            return type("Completion", (), {"choices": [choice], "usage": usage})()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.chat = FakeChat()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    result = OpenAICompatibleTranslator().translate_texts_with_metadata(
        texts=["こんにちは"],
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
        context_snapshot={
            "mangaContext": "都市怪谈感, 语气冷静压抑。",
            "confirmedTranslations": ["学姐"],
            "glossary": {"先輩": "学姐"},
        },
    )

    assert result["translatedTexts"] == ["你好呀"]
    assert [item["name"] for item in result["rounds"]] == ["draft", "contextual", "final"]
    assert result["rounds"][0]["translatedTexts"] == ["你好"]
    assert result["rounds"][1]["translatedTexts"] == ["你好呀"]
    assert result["tokenUsage"] == {
        "inputTokens": 390,
        "outputTokens": 56,
        "totalTokens": 446,
        "estimated": False,
    }
    assert "漫画背景" in captured["messages"][0][1]["content"]
    assert "都市怪谈感" in captured["messages"][0][1]["content"]
    assert "邻近页确认译文" in captured["messages"][1][1]["content"]
    assert "<|1|>你好" in captured["messages"][1][1]["content"]


def test_translate_texts_with_metadata_uses_configured_prompts(monkeypatch):
    captured = {"messages": []}
    responses = [
        ("<|1|>初稿", type("Usage", (), {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15})()),
        ("<|1|>修订", type("Usage", (), {"prompt_tokens": 13, "completion_tokens": 3, "total_tokens": 16})()),
        ("<|1|>定稿", type("Usage", (), {"prompt_tokens": 14, "completion_tokens": 3, "total_tokens": 17})()),
    ]

    class FakeCompletions:
        def create(self, model, messages, stream, timeout=None, temperature=None):
            captured["messages"].append(messages)
            content, usage = responses.pop(0)
            message = type("Message", (), {"content": content})()
            choice = type("Choice", (), {"message": message})()
            return type("Completion", (), {"choices": [choice], "usage": usage})()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.chat = FakeChat()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setattr(
        "src.core.translate.openai_compatible.resolve_translation_prompt_config",
        lambda project_root=None, settings=None: {
            "system": "system override",
            "rounds": {
                "draft": "draft override",
                "contextual": "contextual override",
                "final": "final override",
            },
        },
        raising=False,
    )

    result = OpenAICompatibleTranslator().translate_texts_with_metadata(
        texts=["こんにちは"],
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
    )

    assert result["translatedTexts"] == ["定稿"]
    assert captured["messages"][0][0]["content"] == "system override"
    assert captured["messages"][0][1]["content"].startswith("draft override")
    assert captured["messages"][1][1]["content"].startswith("contextual override")
    assert captured["messages"][2][1]["content"].startswith("final override")


def test_translate_texts_with_metadata_preserves_empty_slots(monkeypatch):
    class FakeCompletions:
        def create(self, model, messages, stream, timeout=None, temperature=None):
            message = type("Message", (), {"content": "<|1|>你好"})()
            choice = type("Choice", (), {"message": message})()
            return type("Completion", (), {"choices": [choice]})()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.chat = FakeChat()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    result = OpenAICompatibleTranslator().translate_texts_with_metadata(
        texts=["", "こんにちは", "  "],
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
    )

    assert result["translatedTexts"] == ["", "你好", ""]
    assert result["rounds"][-1]["translatedTexts"] == ["", "你好", ""]


def test_translate_texts_with_metadata_chunks_large_batches_and_aggregates_usage(monkeypatch):
    captured = {"calls": 0}
    responses = [
        ("<|1|>一1\n<|2|>一2\n<|3|>一3\n<|4|>一4\n<|5|>一5", type("Usage", (), {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})()),
        ("<|1|>甲1\n<|2|>甲2\n<|3|>甲3\n<|4|>甲4\n<|5|>甲5", type("Usage", (), {"prompt_tokens": 110, "completion_tokens": 22, "total_tokens": 132})()),
        ("<|1|>终1\n<|2|>终2\n<|3|>终3\n<|4|>终4\n<|5|>终5", type("Usage", (), {"prompt_tokens": 90, "completion_tokens": 18, "total_tokens": 108})()),
        ("<|1|>二1", type("Usage", (), {"prompt_tokens": 30, "completion_tokens": 8, "total_tokens": 38})()),
        ("<|1|>乙1", type("Usage", (), {"prompt_tokens": 40, "completion_tokens": 9, "total_tokens": 49})()),
        ("<|1|>终6", type("Usage", (), {"prompt_tokens": 25, "completion_tokens": 7, "total_tokens": 32})()),
    ]

    class FakeCompletions:
        def create(self, model, messages, stream, timeout=None, temperature=None):
            captured["calls"] += 1
            content, usage = responses.pop(0)
            message = type("Message", (), {"content": content})()
            choice = type("Choice", (), {"message": message})()
            return type("Completion", (), {"choices": [choice], "usage": usage})()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.chat = FakeChat()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    result = OpenAICompatibleTranslator().translate_texts_with_metadata(
        texts=["a", "b", "c", "d", "e", "f"],
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
    )

    assert captured["calls"] == 6
    assert result["translatedTexts"] == ["终1", "终2", "终3", "终4", "终5", "终6"]
    assert result["rounds"][0]["translatedTexts"] == ["一1", "一2", "一3", "一4", "一5", "二1"]
    assert result["rounds"][1]["translatedTexts"] == ["甲1", "甲2", "甲3", "甲4", "甲5", "乙1"]
    assert result["tokenUsage"] == {
        "inputTokens": 395,
        "outputTokens": 84,
        "totalTokens": 479,
        "estimated": False,
    }


def test_translate_texts_with_metadata_falls_back_to_single_round_for_dense_batch(monkeypatch):
    captured = {"calls": 0}

    class FakeCompletions:
        def create(self, model, messages, stream, timeout=None, temperature=None):
            captured["calls"] += 1
            message = type("Message", (), {"content": "<|1|>甲\n<|2|>乙\n<|3|>丙\n<|4|>丁\n<|5|>戊\n<|6|>己\n<|7|>庚"})()
            choice = type("Choice", (), {"message": message})()
            usage = type("Usage", (), {"prompt_tokens": 70, "completion_tokens": 14, "total_tokens": 84})()
            return type("Completion", (), {"choices": [choice], "usage": usage})()

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, api_key, base_url):
            self.chat = FakeChat()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    result = OpenAICompatibleTranslator().translate_texts_with_metadata(
        texts=["a", "b", "c", "d", "e", "f", "g"],
        model="mimo-v2.5-pro",
        base_url=TEST_BASE_URL,
    )

    assert captured["calls"] == 1
    assert result["translatedTexts"] == ["甲", "乙", "丙", "丁", "戊", "己", "庚"]
    assert [item["name"] for item in result["rounds"]] == ["final"]
    assert result["tokenUsage"]["totalTokens"] == 84
