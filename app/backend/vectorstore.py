"""Local semantic index over the workshop manual.

A thin wrapper around a persistent Chroma collection that embeds manual pages
(chunked into passages) with a local ONNX model — no embedding API, so the
OEM manual text never leaves the machine and the index is free to rebuild.

retrieval.py fuses what `vector_rank()` returns with its keyword scorer; this
module owns everything Chroma-specific so the rest of the backend has no hard
dependency on it. Every entry point degrades to a no-op (returns ``[]`` /
``False``) if chromadb is not installed or the index can't be built, so the
assistant still works keyword-only.
"""
import sys

import config

_COLLECTION = "workshop_manual"
# Reciprocal-rank-fusion-friendly: passages fold back to their source page, so
# we over-fetch passages to fill `n` distinct pages.
_PASSAGES_PER_PAGE_EST = 3


def available() -> bool:
    """True if chromadb can be imported (the optional vector dependency)."""
    try:
        import chromadb  # noqa: F401
        return True
    except Exception:
        return False


def _source_signature() -> str:
    """Identity of the source corpus on disk; the index is stale on change.

    Covers both manuals (workshop + owner's) and the chunk params so adding the
    owner's manual or retuning chunking triggers a rebuild.
    """
    parts = [f"{config.CHUNK_WORDS}:{config.CHUNK_OVERLAP_WORDS}"]
    for path in (config.WORKSHOP_MANUAL, config.OWNERS_MANUAL):
        if path.exists():
            st = path.stat()
            parts.append(f"{path.name}={st.st_size}:{int(st.st_mtime)}")
    return "|".join(parts)


def _chunk(text: str):
    """Split a page into overlapping word windows (see config.CHUNK_WORDS)."""
    words = text.split()
    if not words:
        return []
    step = max(1, config.CHUNK_WORDS - config.CHUNK_OVERLAP_WORDS)
    chunks = []
    for start in range(0, len(words), step):
        window = words[start:start + config.CHUNK_WORDS]
        if window:
            chunks.append(" ".join(window))
        if start + config.CHUNK_WORDS >= len(words):
            break
    return chunks


# Cache the live client/collection across calls within a process.
_client = None
_collection_handle = None


def _get_collection(build_if_stale: bool = True):
    """Return a ready collection, (re)building it if missing or stale.

    Returns None if chromadb is unavailable or anything goes wrong — callers
    treat None as "no vector search available" and fall back to keyword.
    """
    global _client, _collection_handle
    if _collection_handle is not None:
        return _collection_handle
    if not available():
        return None
    try:
        import chromadb

        config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(config.INDEX_DIR))
        sig = _source_signature()
        coll = _client.get_or_create_collection(_COLLECTION)
        if build_if_stale and (coll.metadata or {}).get("source_sig") != sig:
            coll = _build(_client, sig)
        _collection_handle = coll
        return coll
    except Exception as e:  # pragma: no cover - environment dependent
        print(f"[vectorstore] disabled: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _build(client, sig: str):
    """(Re)embed every manual page into a fresh collection."""
    import retrieval  # lazy: retrieval imports this module at top level

    client.delete_collection(_COLLECTION)
    coll = client.create_collection(_COLLECTION, metadata={"source_sig": sig})

    corpus = retrieval._corpus()
    ids, docs, metas = [], [], []
    for rec in corpus:
        for ci, passage in enumerate(_chunk(rec["text"])):
            ids.append(f"{rec['id']}-{ci}")
            docs.append(passage)
            metas.append({
                "doc_id": rec["id"],
                "source": rec["source"],
                "section": rec["section"] or "",
                "chapter": rec["chapter"] or "",
                "page": rec["page"] if rec["page"] is not None else -1,
            })

    print(f"[vectorstore] embedding {len(docs)} passages from "
          f"{len(corpus)} documents…", file=sys.stderr)
    for i in range(0, len(docs), 512):  # batch so the ONNX model stays bounded
        coll.add(ids=ids[i:i + 512], documents=docs[i:i + 512],
                 metadatas=metas[i:i + 512])
    print(f"[vectorstore] index ready ({coll.count()} passages).", file=sys.stderr)
    return coll


def vector_rank(query: str, n: int = 5):
    """Semantic search; returns up to `n` distinct corpus documents best→worst.

    Each item: {"id", "source", "section", "chapter", "page", "passage"} where
    `passage` is the chunk that matched (a ready-made snippet). `id` is the
    corpus id retrieval.py fuses on. Empty list if vector search is unavailable.
    """
    coll = _get_collection()
    if coll is None:
        return []
    try:
        res = coll.query(query_texts=[query], n_results=n * _PASSAGES_PER_PAGE_EST)
    except Exception as e:  # pragma: no cover
        print(f"[vectorstore] query failed: {type(e).__name__}: {e}", file=sys.stderr)
        return []

    metas = (res.get("metadatas") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    ranked, seen = [], set()
    for meta, doc in zip(metas, docs):
        did = meta.get("doc_id")
        if did in seen:
            continue  # keep best-ranked passage per document only
        seen.add(did)
        page = meta.get("page", -1)
        ranked.append({
            "id": did,
            "source": meta.get("source") or "workshop",
            "section": meta.get("section") or None,
            "chapter": meta.get("chapter") or None,
            "page": page if page != -1 else None,
            "passage": doc,
        })
        if len(ranked) >= n:
            break
    return ranked


def build(force: bool = False) -> bool:
    """Build/refresh the index explicitly (used by the CLI entry point)."""
    global _collection_handle
    if not available():
        print("[vectorstore] chromadb not installed — nothing to build.",
              file=sys.stderr)
        return False
    _collection_handle = None  # force a fresh handle
    if force:
        try:
            import chromadb
            chromadb.PersistentClient(path=str(config.INDEX_DIR)).delete_collection(_COLLECTION)
        except Exception:
            pass
    return _get_collection(build_if_stale=True) is not None


if __name__ == "__main__":
    ok = build(force="--force" in sys.argv)
    sys.exit(0 if ok else 1)
