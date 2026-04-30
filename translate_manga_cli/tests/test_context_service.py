from src.core.context.service import build_context_snapshot


def test_build_context_snapshot_prefers_manual_confirmed_translations():
    pages = [
        {"id": "page-0001", "fileName": "001.jpg"},
        {"id": "page-0002", "fileName": "002.jpg"},
    ]
    results = {
        "page-0001": {
            "manualEdited": True,
            "bubbleStates": [{"originalText": "先輩", "translatedText": "学姐"}],
        }
    }

    snapshot = build_context_snapshot(pages, results, current_page_id="page-0002")

    assert "学姐" in snapshot["confirmedTranslations"]
    assert snapshot["glossary"]["先輩"] == "学姐"
    assert snapshot["mangaContext"] == ""
