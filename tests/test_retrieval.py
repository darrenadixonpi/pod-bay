"""Tests for the retrieval scorers in app/backend/retrieval.py.

These cover the pure text helpers (tokenisation, query-term extraction, snippet
windowing, the section char-cap) and the ranking machinery (BM25 ordering, the
reciprocal-rank-fusion in search_manual, owner's-manual TOC parsing, and the
page-windowed get_section). The corpus-dependent functions are exercised against
a small synthetic corpus injected via monkeypatch, so no vehicle data is needed.
"""
import config
import retrieval
import vectorstore


# ──────────────────────────────────────────────────────────────────────────────
# _tokenize / _query_terms
# ──────────────────────────────────────────────────────────────────────────────

def test_tokenize_splits_and_lowercases():
    assert retrieval._tokenize("Section 06-03: Brakes!") == ["section", "06", "03", "brakes"]


def test_query_terms_drops_stopwords_dedups_keeps_order():
    terms = retrieval._query_terms("How do I remove the front brake caliper and the caliper")
    assert terms == ["remove", "front", "brake", "caliper"]


def test_query_terms_keeps_directional_words():
    # "front"/"rear" discriminate in this domain and are deliberately NOT stopwords.
    assert "front" in retrieval._query_terms("front wheel bearing")
    assert "rear" in retrieval._query_terms("rear main seal")


# ──────────────────────────────────────────────────────────────────────────────
# _cap
# ──────────────────────────────────────────────────────────────────────────────

def test_cap_under_limit_is_untouched():
    text = "short text"
    assert retrieval._cap(text, 100) == (text, False)


def test_cap_trims_on_newline_boundary():
    text = "abcdefghij\nklmnopqrstuvwxyz"  # newline at index 10
    out, truncated = retrieval._cap(text, 20)
    assert truncated is True
    assert out == "abcdefghij"  # cut at the newline, trailing ws stripped


def test_cap_hard_cut_when_no_nearby_newline():
    text = "a" * 30  # no newline at all
    out, truncated = retrieval._cap(text, 20)
    assert truncated is True
    assert out == "a" * 20


# ──────────────────────────────────────────────────────────────────────────────
# _snippet
# ──────────────────────────────────────────────────────────────────────────────

def test_snippet_centers_on_present_term():
    text = ("intro padding " * 40) + "the caliper bolt torque" + (" tail padding" * 40)
    snip = retrieval._snippet(text, ["caliper"], width=60)
    assert "caliper" in snip


def test_snippet_falls_back_to_passage_when_term_absent():
    snip = retrieval._snippet("nothing relevant here", ["caliper"], width=10, passage="VECTORPASSAGE")
    assert snip.startswith("VECTORPASSAGE"[:10])


def test_snippet_falls_back_to_head_without_passage():
    snip = retrieval._snippet("abcdefghijklmnop", ["zzz"], width=5)
    assert snip == "abcde"


# ──────────────────────────────────────────────────────────────────────────────
# BM25 ranking (synthetic corpus)
# ──────────────────────────────────────────────────────────────────────────────

SYNTH_CORPUS = [
    {"id": "W1", "source": "workshop", "section": "06-03", "chapter": None,
     "page": 12, "text": "brake caliper removal and torque specification for the front disc"},
    {"id": "W2", "source": "workshop", "section": "01-02", "chapter": None,
     "page": 40, "text": "engine oil change interval and routine maintenance schedule"},
    {"id": "O0", "source": "owners", "section": None, "chapter": "Maintenance",
     "page": None, "text": "tire pressure fluid levels and maintenance schedule overview"},
]


def _patch_corpus(monkeypatch, corpus=SYNTH_CORPUS):
    monkeypatch.setattr(retrieval, "_corpus", lambda vid=None: corpus)
    monkeypatch.setattr(retrieval, "_corpus_by_id", lambda vid=None: {d["id"]: d for d in corpus})
    retrieval._bm25_stats.cache_clear()


def test_bm25_stats_basic_shape(monkeypatch):
    _patch_corpus(monkeypatch)
    doc_tf, doc_len, idf, avgdl, n = retrieval._bm25_stats("_test")
    assert n == 3
    assert avgdl > 0
    assert all(v >= 0 for v in idf.values())  # +1 inside the log keeps idf >= 0
    assert "caliper" in idf


def test_keyword_rank_finds_unique_term(monkeypatch):
    _patch_corpus(monkeypatch)
    ranked = retrieval._keyword_rank("caliper", 5, "_test")
    assert ranked[0]["id"] == "W1"  # only doc mentioning "caliper"


def test_keyword_rank_orders_by_relevance(monkeypatch):
    _patch_corpus(monkeypatch)
    # "maintenance schedule" appears in both W2 and O0; both should rank above the
    # unrelated brake page, which shouldn't appear at all (no term overlap).
    ranked = retrieval._keyword_rank("maintenance schedule", 5, "_test")
    ids = [d["id"] for d in ranked]
    assert set(ids) == {"W2", "O0"}
    assert "W1" not in ids


def test_keyword_rank_empty_for_stopword_only_query(monkeypatch):
    _patch_corpus(monkeypatch)
    assert retrieval._keyword_rank("how do I", 5, "_test") == []


# ──────────────────────────────────────────────────────────────────────────────
# search_manual — reciprocal rank fusion
# ──────────────────────────────────────────────────────────────────────────────

def test_search_manual_fuses_keyword_and_vector(monkeypatch):
    _patch_corpus(monkeypatch)
    by_id = {d["id"]: d for d in SYNTH_CORPUS}

    # Keyword ranks W1 then W2; vector ranks W1 then O0. W1 is rank-0 in BOTH,
    # so RRF must place it first.
    monkeypatch.setattr(retrieval, "_keyword_rank",
                        lambda q, depth, vid: [by_id["W1"], by_id["W2"]])
    monkeypatch.setattr(vectorstore, "available", lambda: True)
    monkeypatch.setattr(vectorstore, "vector_rank",
                        lambda q, depth, vid: [{"id": "W1", "passage": "p1"},
                                               {"id": "O0", "passage": "p0"}])
    monkeypatch.setattr(config, "SEARCH_MODE", "hybrid")

    out = retrieval.search_manual("brake caliper torque", max_results=3, vehicle_id="_test")
    ids_in_order = []
    for r in out["results"]:
        # locator carries section+page (workshop) or chapter (owners); map back to id
        if r["source"] == "workshop":
            ids_in_order.append(next(d["id"] for d in SYNTH_CORPUS
                                     if d["section"] == r["section"] and d["page"] == r["page"]))
        else:
            ids_in_order.append(next(d["id"] for d in SYNTH_CORPUS
                                     if d["chapter"] == r["chapter"]))
    assert ids_in_order[0] == "W1"
    assert out["result_count"] == len(out["results"])
    assert set(ids_in_order) == {"W1", "W2", "O0"}
    assert all("snippet" in r for r in out["results"])


def test_search_manual_respects_max_results(monkeypatch):
    _patch_corpus(monkeypatch)
    by_id = {d["id"]: d for d in SYNTH_CORPUS}
    monkeypatch.setattr(retrieval, "_keyword_rank",
                        lambda q, depth, vid: [by_id["W1"], by_id["W2"], by_id["O0"]])
    monkeypatch.setattr(vectorstore, "available", lambda: False)
    monkeypatch.setattr(config, "SEARCH_MODE", "keyword")
    out = retrieval.search_manual("maintenance", max_results=1, vehicle_id="_test")
    assert len(out["results"]) == 1


def test_search_manual_locator_shape(monkeypatch):
    _patch_corpus(monkeypatch)
    by_id = {d["id"]: d for d in SYNTH_CORPUS}
    monkeypatch.setattr(retrieval, "_keyword_rank", lambda q, depth, vid: [by_id["W1"]])
    monkeypatch.setattr(vectorstore, "available", lambda: False)
    monkeypatch.setattr(config, "SEARCH_MODE", "keyword")
    out = retrieval.search_manual("caliper", max_results=5, vehicle_id="_test")
    r = out["results"][0]
    assert r["source"] == "workshop"
    assert r["section"] == "06-03"
    assert r["page"] == 12


# ──────────────────────────────────────────────────────────────────────────────
# derive_owners_chapters — Table of Contents parsing
# ──────────────────────────────────────────────────────────────────────────────

def test_derive_owners_chapters_reads_dot_leaders_in_order():
    toc = (
        "Owner Guide\n"
        "Table of Contents\n"
        "Introduction .......... 1\n"
        "Instrument Cluster ..... 12\n"
        "Maintenance ............ 47\n"
        "\n"
        "Introduction\n"
        "Welcome to your vehicle...\n"
    )
    assert retrieval.derive_owners_chapters(toc) == [
        "Introduction", "Instrument Cluster", "Maintenance"]


def test_derive_owners_chapters_empty_without_toc():
    assert retrieval.derive_owners_chapters("no contents heading here\njust prose") == []


# ──────────────────────────────────────────────────────────────────────────────
# get_section — page-windowed reads
# ──────────────────────────────────────────────────────────────────────────────

def _patch_pages(monkeypatch):
    pages = [{"page": p, "section": "06-03", "text": f"PAGE {p} body text"}
             for p in range(10, 21)]  # pages 10..20 inclusive (11 pages)
    monkeypatch.setattr(retrieval, "_pages", lambda vid=None: pages)
    monkeypatch.setattr(retrieval, "_section_index",
                        lambda vid=None: [{"section": "06-03", "name": "Brakes",
                                           "page_count": 11, "first_page": 10, "last_page": 20}])
    monkeypatch.setattr(retrieval, "_owners_chapters", lambda vid=None: [
        {"chapter": "Maintenance", "text": "Maintenance chapter body."}])
    return pages


def test_get_section_windows_around_page(monkeypatch):
    _patch_pages(monkeypatch)
    out = retrieval.get_section("06-03", vehicle_id="_test", around_page=15)
    assert out["found"] is True
    assert out["source"] == "workshop"
    assert out["name"] == "Brakes"
    # window = 2 before + around + 3 after => pages 13..18
    assert out["returned_pages"] == [13, 18]
    assert out["section_page_range"] == [10, 20]
    assert "note" in out  # because the window is a subset of the section


def test_get_section_from_start_without_around_page(monkeypatch):
    _patch_pages(monkeypatch)
    out = retrieval.get_section("06-03", vehicle_id="_test")
    assert out["found"] is True
    assert out["returned_pages"][0] == 10  # starts at the section's first page


def test_get_section_owners_chapter(monkeypatch):
    _patch_pages(monkeypatch)
    out = retrieval.get_section("Maintenance", vehicle_id="_test")
    assert out["found"] is True
    assert out["source"] == "owners"
    assert "Maintenance chapter body." in out["text"]


def test_get_section_unknown_section(monkeypatch):
    _patch_pages(monkeypatch)
    out = retrieval.get_section("99-99", vehicle_id="_test")
    assert out["found"] is False
    assert "06-03" in out["available_sections"]
