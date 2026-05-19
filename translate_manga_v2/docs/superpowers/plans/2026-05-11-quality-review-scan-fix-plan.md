# Quality Review Scan Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional full-book translation quality review pass to menu option 3, then reuse the existing retry-review-pages overwrite flow.

**Architecture:** Keep hard-error scanning unchanged. Add a focused `quality_review` helper that reads existing debug records, asks the translation model to flag soft translation issues, writes `_debug/quality-review.tsv`, and exposes those entries to the existing menu retry collector.

**Tech Stack:** Python 3.10, pytest, OpenAI-compatible chat API through the existing translator settings, V2 `_debug` artifacts.

---

### Task 1: Quality Review TSV And Parsing

**Files:**
- Create: `src/translate_manga/cli/quality_review.py`
- Test: `tests/test_quality_review.py`

- [x] Write tests for parsing model output into review entries and writing `quality-review.tsv`.
- [x] Run `pytest tests/test_quality_review.py -q` and verify RED.
- [x] Implement minimal parser/writer helpers.
- [x] Re-run `pytest tests/test_quality_review.py -q`.

### Task 2: Model Review Pass

**Files:**
- Modify: `src/translate_manga/cli/quality_review.py`
- Test: `tests/test_quality_review.py`

- [x] Write tests for chunking debug records and invoking an injected reviewer client without touching the real API.
- [x] Run targeted tests and verify RED.
- [x] Implement `run_quality_review(output_dir, ...)` with dependency injection for tests.
- [x] Re-run targeted tests.

### Task 3: Menu 3 Integration

**Files:**
- Modify: `src/translate_manga/cli/menu.py`
- Test: `tests/test_cli_menu.py`

- [x] Write tests that menu option 3 can include quality-review entries in retry scan.
- [x] Run targeted menu tests and verify RED.
- [x] Add scan mode prompt and merge `_debug/quality-review.tsv` entries into `_collect_review_entries`.
- [x] Re-run targeted menu tests.

### Task 4: Verification And Docs

**Files:**
- Modify: `README.md`
- Modify: `start.md`
- Modify: `docs/refactor_phase3_retry_review_pages_plan.md`

- [x] Update docs to explain menu 3 hard-error vs full-book review modes.
- [x] Run `python -m pytest -q`.
- [x] Run a no-API unit verification; avoid real manga directories while existing BAT is running.

## Completion Notes

- Added `src/translate_manga/cli/quality_review.py` for `_debug/pages/*.json` based translation QA, strict JSON/TSV parsing, and `_debug/quality-review.tsv` persistence.
- Menu option 3 now asks for scan mode: hard-error-only or hard errors plus full-book quality review.
- Quality review pages are only consumed when the quality-review retry path is explicitly enabled, so ordinary hard-error retry is not affected by stale soft-review TSV files.
- Multi-book scans skip quality review only for books that still have hard errors; clean books in the same batch can continue to quality review.
- Verification: `.venv310/Scripts/python.exe -m pytest -q` -> `192 passed`; `compileall` completed without errors.
