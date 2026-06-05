"""Local semantic index over the workshop manual.

A thin wrapper around a persistent Chroma collection that embeds manual pages
(chunked into passages) with a local ONNX model — no embedding API, so the
OEM manual text never leaves the machine and the index is free to rebuild.

retrieval.py fuses what `vector_rank()` returns with its keyword scorer; this
module owns everything Chroma-specific so the rest of the backend has no hard
dependency on it. Every entry point degrades to a no-op (returns ``[]`` /
``False``) if chromadb is not installed or the index can't be built, so the
assistant still works keyword-only.

Indexes are per-vehicle: each vehicle has its own persisted collection under
vehicles/<id>/.index/, and live handles are cached per vehicle id.
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


def _source_signature(vehicle) -> str:
    """Identity of a vehicle's source corpus on disk; index is stale on change.

    Covers both manuals (workshop + owner's) and the chunk params so adding the
    owner's manual or retuning chunking triggers a rebuild.
    """
    parts = [f"{config.CHUNK_WORDS}:{config.CHUNK_OVERLAP_WORDS}"]
    for path in (vehicle.workshop_manual, vehicle.owners_manual):
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


# Live client/collection handles, cached per vehicle id within a process.
_clients = {}
_collections = {}


def _get_collection(vehicle_id, build_if_stale: bool = True):
    """Return a vehicle's ready collection, (re)building it if missing or stale.

    Returns None if chromadb is unavailable or anything goes wrong — callers
    treat None as "no vector search available" and fall back to keyword.
    """
    if vehicle_id in _collections:
        return _collections[vehicle_id]
    if not available():
        return None
    try:
        import chromadb

        vehicle = config.get_vehicle(vehicle_id)
        vehicle.index_dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(vehicle.index_dir))
        _clients[vehicle.id] = client
        sig = _source_signature(vehicle)
        coll = client.get_or_create_collection(_COLLECTION)
        if build_if_stale and (coll.metadata or {}).get("source_sig") != sig:
            coll = _build(client, vehicle, sig)
        _collections[vehicle.id] = coll
        return coll
    except Exception as e:  # pragma: no cover - environment dependent
        print(f"[vectorstore] disabled for {vehicle_id}: {type(e).__name__}: {e}",
              file=sys.stderr)
        return None


def _build(client, vehicle, sig: str):
    """(Re)embed every manual page for a vehicle into a fresh collection."""
    import retrieval  # lazy: retrieval imports this module at top level

    client.delete_collection(_COLLECTION)
    coll = client.create_collection(_COLLECTION, metadata={"source_sig": sig})

    corpus = retrieval._corpus(vehicle.id)
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

    print(f"[vectorstore] {vehicle.id}: embedding {len(docs)} passages from "
          f"{len(corpus)} documents…", file=sys.stderr)
    for i in range(0, len(docs), 512):  # batch so the ONNX model stays bounded
        coll.add(ids=ids[i:i + 512], documents=docs[i:i + 512],
                 metadatas=metas[i:i + 512])
    print(f"[vectorstore] {vehicle.id}: index ready ({coll.count()} passages).",
          file=sys.stderr)
    return coll


def vector_rank(query: str, n: int = 5, vehicle_id=None):
    """Semantic search; returns up to `n` distinct corpus documents best→worst.

    Each item: {"id", "source", "section", "chapter", "page", "passage"} where
    `passage` is the chunk that matched (a ready-made snippet). `id` is the
    corpus id retrieval.py fuses on. Empty list if vector search is unavailable.
    """
    coll = _get_collection(vehicle_id)
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


def build(vehicle_id=None, force: bool = False) -> bool:
    """Build/refresh one vehicle's index explicitly (used by the CLI)."""
    if not available():
        print("[vectorstore] chromadb not installed — nothing to build.",
              file=sys.stderr)
        return False
    vehicle = config.get_vehicle(vehicle_id)
    _collections.pop(vehicle.id, None)  # drop any cached handle
    if force:
        try:
            import chromadb
            chromadb.PersistentClient(path=str(vehicle.index_dir)).delete_collection(_COLLECTION)
        except Exception:
            pass
    return _get_collection(vehicle.id, build_if_stale=True) is not None


if __name__ == "__main__":
    # Build/refresh every extracted vehicle's index.
    force = "--force" in sys.argv
    ok = True
    for v in config.available_vehicles():
        ok = build(v["id"], force=force) and ok
    sys.exit(0 if ok else 1)
