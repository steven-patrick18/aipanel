"""ARQ job: parse → chunk → embed → upsert into pgvector.

Real implementation as of v0.12. Replaces the v0.7 stub that just flipped
status. PDF / DOCX / TXT / MD all supported via the parser shim below.

Failure modes that we explicitly catch + record on the document row:
- unsupported file format            → status='error', error_msg set
- parse error (corrupt PDF, etc.)    → status='error', error_msg set
- empty document (no extractable text) → status='ready', chunk_count=0
- embed-server unreachable           → status='error', error_msg set
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
from typing import Iterable

import psycopg
import structlog

from ..config import get_config
from ..integrations.embed_client import EmbedClient

log = structlog.get_logger().bind(component="kb_ingest_job")

# Tunables.
CHUNK_TARGET_TOKENS  = 380     # comfortably under 512 for most embed models
CHUNK_OVERLAP_TOKENS = 60      # tail overlap reduces boundary loss
EMBED_BATCH_SIZE     = 32      # match embed-server max_batch


# ===========================================================================
# Parsers
# ===========================================================================

def _parse_txt(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf not installed; pip install pypdf") from exc
    reader = PdfReader(io.BytesIO(raw))
    out: list[str] = []
    for page in reader.pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n\n".join(t for t in out if t)


def _parse_docx(raw: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("python-docx not installed; pip install python-docx") from exc
    doc = Document(io.BytesIO(raw))
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def _parse(filename: str, raw: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return _parse_pdf(raw)
    if name.endswith(".docx"):
        return _parse_docx(raw)
    if name.endswith((".txt", ".md", ".rst", ".log")):
        return _parse_txt(raw)
    # Default: assume text. Sniff for binary content first.
    sample = raw[:4096]
    nontext = sum(1 for b in sample if b < 9 or (13 < b < 32))
    if nontext > len(sample) // 10:
        raise RuntimeError(
            f"unsupported file format: {filename} (looks binary; "
            "supported: pdf, docx, txt, md)"
        )
    return _parse_txt(raw)


# ===========================================================================
# Chunker — sliding window with sentence-boundary preference
# ===========================================================================

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n\n+")


def _approx_tokens(text: str) -> int:
    """Cheap token estimate. Real tokenisation lives in the embed-server."""
    return max(1, len(text) // 4)


def _chunk(text: str,
           target: int = CHUNK_TARGET_TOKENS,
           overlap: int = CHUNK_OVERLAP_TOKENS) -> Iterable[str]:
    """Sliding window over sentence boundaries.

    Greedily appends sentences until the token target is hit. The next
    chunk starts ``overlap`` tokens worth of tail from the prior chunk so
    a fact split across the boundary is still discoverable.
    """
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return

    sents = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    if not sents:
        return

    cur: list[str] = []
    cur_tok = 0
    for s in sents:
        s_tok = _approx_tokens(s)
        if cur and cur_tok + s_tok > target:
            yield " ".join(cur)
            tail: list[str] = []
            tail_tok = 0
            for prev in reversed(cur):
                ptk = _approx_tokens(prev)
                if tail_tok + ptk > overlap:
                    break
                tail.append(prev)
                tail_tok += ptk
            cur = list(reversed(tail))
            cur_tok = tail_tok
        cur.append(s)
        cur_tok += s_tok
    if cur:
        yield " ".join(cur)


# ===========================================================================
# DB helpers (sync — psycopg)
# ===========================================================================

_DELETE_PRIOR = "DELETE FROM kb_chunks WHERE document_id = %s"

_INSERT_CHUNK = (
    "INSERT INTO kb_chunks "
    "(document_id, kb_id, chunk_index, chunk_text, chunk_tokens, embedding) "
    "VALUES (%s, %s, %s, %s, %s, %s::vector)"
)

_UPDATE_DOC_OK = (
    "UPDATE kb_documents "
    "   SET status = 'ready', chunk_count = %s, bytes_total = %s, "
    "       error_msg = NULL "
    " WHERE id = %s"
)

_UPDATE_DOC_ERR = (
    "UPDATE kb_documents "
    "   SET status = 'error', error_msg = %s "
    " WHERE id = %s"
)

_UPDATE_DOC_PROCESSING = (
    "UPDATE kb_documents SET status = 'processing' WHERE id = %s"
)


def _vec_literal(v: list[float]) -> str:
    """pgvector accepts the canonical '[1.0,2.0,...]' string."""
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


def _sync_replace_chunks(
    db_dsn: str,
    *,
    document_id: str,
    kb_id: str,
    chunks: list[tuple[int, str, int, list[float]]],
    bytes_total: int,
) -> None:
    with psycopg.connect(db_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(_DELETE_PRIOR, (document_id,))
            for idx, text, tokens, vec in chunks:
                cur.execute(
                    _INSERT_CHUNK,
                    (document_id, kb_id, idx, text, tokens, _vec_literal(vec)),
                )
            cur.execute(_UPDATE_DOC_OK,
                        (len(chunks), bytes_total, document_id))


def _sync_mark_status(db_dsn: str, document_id: str, sql: str, *args) -> None:
    with psycopg.connect(db_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (*args, document_id))


# ===========================================================================
# Public ARQ entrypoint
# ===========================================================================

async def kb_ingest_document(
    ctx: dict,
    document_id: str,
    kb_id: str,
    filename: str,
    content_b64: str,
) -> dict:
    cfg = get_config()
    embed_url = (
        getattr(getattr(cfg, "embed", None), "endpoint", None)
        or "http://127.0.0.1:8004"
    )
    db_dsn    = cfg.database.dsn
    raw = base64.b64decode(content_b64)
    bytes_total = len(raw)

    log.info("kb_ingest_start",
             document_id=document_id, kb_id=kb_id,
             filename=filename, bytes=bytes_total)

    await asyncio.to_thread(_sync_mark_status, db_dsn,
                            document_id, _UPDATE_DOC_PROCESSING)

    # 1. Parse.
    try:
        text = _parse(filename, raw)
    except Exception as exc:
        log.warning("kb_parse_failed",
                    document_id=document_id, error=str(exc))
        await asyncio.to_thread(_sync_mark_status, db_dsn,
                                document_id, _UPDATE_DOC_ERR, str(exc)[:500])
        return {"ok": False, "stage": "parse", "error": str(exc)}

    # 2. Chunk.
    chunks_text = list(_chunk(text))
    if not chunks_text:
        await asyncio.to_thread(_sync_replace_chunks,
                                db_dsn,
                                document_id=document_id, kb_id=kb_id,
                                chunks=[], bytes_total=bytes_total)
        log.info("kb_ingest_empty", document_id=document_id)
        return {"ok": True, "chunks": 0, "note": "empty document"}

    log.info("kb_chunked", document_id=document_id, chunks=len(chunks_text))

    # 3. Embed (batched).
    embed = EmbedClient(embed_url)
    try:
        all_vecs: list[list[float]] = []
        for i in range(0, len(chunks_text), EMBED_BATCH_SIZE):
            batch = chunks_text[i : i + EMBED_BATCH_SIZE]
            vecs = await embed.embed_batch(batch)
            if vecs is None:
                raise RuntimeError("embed-server unreachable or returned error")
            all_vecs.extend(vecs)
    except Exception as exc:
        await asyncio.to_thread(_sync_mark_status, db_dsn,
                                document_id, _UPDATE_DOC_ERR,
                                f"embed: {exc}"[:500])
        await embed.aclose()
        return {"ok": False, "stage": "embed", "error": str(exc)}
    finally:
        await embed.aclose()

    # 4. Upsert.
    chunks_for_db = [
        (i, txt, _approx_tokens(txt), vec)
        for i, (txt, vec) in enumerate(zip(chunks_text, all_vecs))
    ]
    try:
        await asyncio.to_thread(_sync_replace_chunks,
                                db_dsn,
                                document_id=document_id, kb_id=kb_id,
                                chunks=chunks_for_db,
                                bytes_total=bytes_total)
    except Exception as exc:
        log.exception("kb_db_write_failed", document_id=document_id)
        await asyncio.to_thread(_sync_mark_status, db_dsn,
                                document_id, _UPDATE_DOC_ERR,
                                f"db write: {exc}"[:500])
        return {"ok": False, "stage": "db", "error": str(exc)}

    log.info("kb_ingest_done",
             document_id=document_id, chunks=len(chunks_text))
    return {"ok": True, "chunks": len(chunks_text)}
