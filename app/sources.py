"""C4 Sources: the user's own .txt/.md files as context.

Upload → split into chunks → (step by step) embed + extract facts for the user to confirm.
Search → nearest chunks by embedding (pgvector), always filtered by user_id.
Processing is done in small steps driven by the page (HTMX polling), so it works on Cloud Run
without background workers.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel

from app import llm
from app.db import connection
from app.pipeline.common import prompt, to_json

EMBED_MODEL = "google/gemini-embedding-2"
EMBED_DIMS = 768
MAX_BYTES = 25 * 1024 * 1024  # Cloud Run takes requests up to 32 MB
MAX_FILES = 20
MAX_CHUNKS = 4000  # ≈ 5.6 M characters after filtering; keeps one file under ~$1 to read
CHUNK_CHARS = 1400  # ≈ 350 tokens (eval: smaller chunks rank the right passage higher)
OVERLAP_CHARS = 250
BATCH = 8  # chunks per LLM call
PARALLEL = 3  # LLM calls per step

Category = Literal["injury", "health", "medication", "goal", "race", "gear", "preference", "life"]


class FileFact(BaseModel):
    category: Category
    text: str
    quote: str


class FileFacts(BaseModel):
    facts: list[FileFact]


class SourceError(Exception):
    pass


# --- chunking ----------------------------------------------------------------------------

def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Paragraph-aware chunks of about `size` characters; the tail of each chunk is repeated at
    the start of the next so facts that cross a boundary are not lost."""
    paras = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        while len(p) > size:  # very long paragraph: hard split
            head, p = p[:size], p[size - overlap:]
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(head)
        if cur and len(cur) + len(p) + 2 > size:
            chunks.append(cur)
            cur = cur[-overlap:].split(" ", 1)[-1] + "\n\n" + p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


# A full ChatGPT export has hundreds of chats (code, travel, work). Above RELEVANT_FROM chats we
# keep only those that mention sport, health, food or the body (UA/EN word stems), which cuts
# size and cost and keeps search on topic.
RELEVANT_FROM = 30
TOPIC_STEMS = ("run", "marathon", "train", "workout", "garmin", "strava", "intervals", "knee",
               "injur", "pain", "health", "doctor", "sleep", "hrv", "diet", "food", "meal",
               "calor", "protein", "weight", "vitamin", "medic", "pill", "swim", "bike", "cycl",
               "triath", "ironman", "gym", "stretch", "muscle", "heart", "blood", "біг", "бiг",
               "марафон", "тренув", "колін", "травм", "біль", "болить", "здоров", "лікар",
               "сон", "спав", "дієт", "їж", "калор", "білок", "вага", "вітамін", "лік",
               "плав", "велосип", "тріатлон", "зал", "розтяж", "м'яз", "мяз", "серц", "кров",
               "аналіз")


def _on_topic(text: str) -> bool:
    low = text.lower()
    return sum(low.count(s) for s in TOPIC_STEMS) >= 3


def json_to_text(text: str) -> str:
    """ChatGPT `conversations.json` → readable "## title / You: … / ChatGPT: …" text (only
    sport and health chats for a big export). Any other JSON is pretty-printed so it can still
    be chunked and searched."""
    import json

    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, list) and data and isinstance(data[0], dict) and "mapping" in data[0]:
        parts = []
        for conv in data:
            msgs = []
            for node in (conv.get("mapping") or {}).values():
                m = (node or {}).get("message") or {}
                role = (m.get("author") or {}).get("role")
                content = (m.get("content") or {}).get("parts") or []
                body = " ".join(p for p in content if isinstance(p, str)).strip()
                if role in ("user", "assistant") and body:
                    msgs.append((m.get("create_time") or 0, role, body))
            msgs.sort(key=lambda x: x[0] or 0)
            lines = [f"**{'You' if r == 'user' else 'ChatGPT'}:** {b}" for _, r, b in msgs]
            if lines:
                parts.append(f"## {conv.get('title') or 'Conversation'}\n\n" + "\n\n".join(lines))
        if len(parts) > RELEVANT_FROM:
            parts = [p for p in parts if _on_topic(p)]
        return "\n\n---\n\n".join(parts)
    return json.dumps(data, ensure_ascii=False, indent=1)


def decode(raw: bytes) -> str:
    """UTF-8 (most exports), UTF-16 only with a BOM, else Windows-1251 (old Ukrainian files)."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")


# --- embeddings and search ---------------------------------------------------------------

def embed(texts: list[str], user_id: str | None = None) -> list[list[float]]:
    """Embeddings on the user's own key when they have one (guests must), else the app's."""
    llm.check_budget(user_id)
    out = []
    for i in range(0, len(texts), 64):
        r = llm.client_for(user_id).embeddings.create(model=EMBED_MODEL, input=texts[i:i + 64],
                                                      dimensions=EMBED_DIMS)
        out += [d.embedding for d in r.data]
    return out


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def search(user_id: str, query: str, k: int = 5) -> list[dict]:
    """Top-k chunks of this user's files for `query`: [{filename, text, score}]."""
    with connection() as c:
        has = c.execute("select 1 from chunks where user_id = %s and embedding is not null limit 1",
                        (user_id,)).fetchone()
        if not has:
            return []
        q = _vec(embed([query], user_id)[0])
        rows = c.execute(
            """select s.filename, ch.text, 1 - (ch.embedding <=> %s::vector) as score
               from chunks ch join sources s on s.id = ch.source_id
               where ch.user_id = %s and ch.embedding is not null
               order by ch.embedding <=> %s::vector limit %s""",
            (q, user_id, q, k)).fetchall()
    return [{"filename": r["filename"], "text": r["text"], "score": round(float(r["score"]), 3)}
            for r in rows]


def excerpts(user_id: str, query: str, k: int = 4, chars: int = 900) -> list[str]:
    """Short excerpts for prompts, labelled with the file name."""
    try:
        return [f"[{h['filename']}] {h['text'][:chars]}" for h in search(user_id, query, k)]
    except Exception:  # search must never break a chat turn
        llm.langfuse.flush()
        return []


# --- upload and step-wise processing -----------------------------------------------------

def add_source(user_id: str, filename: str, raw: bytes) -> int:
    name = (filename or "file.txt").rsplit("/", 1)[-1][:120]
    if not name.lower().endswith((".txt", ".md", ".markdown", ".json")):
        raise SourceError(f"{name}: only .txt, .md and .json files are supported.")
    if len(raw) > MAX_BYTES:
        raise SourceError(f"{name}: larger than 25 MB. Split it into parts.")
    text = decode(raw).strip()
    if name.lower().endswith(".json"):
        text = json_to_text(text)
    if not text:
        raise SourceError(f"{name}: the file is empty.")
    chunks = chunk_text(text)
    if len(chunks) > MAX_CHUNKS:
        raise SourceError(f"{name}: too long to read ({len(chunks)} parts, max {MAX_CHUNKS}). "
                          "Upload a smaller part, e.g. one ChatGPT project.")
    with connection() as c:
        n = c.execute("select count(*) as n from sources where user_id = %s",
                      (user_id,)).fetchone()["n"]
        if n >= MAX_FILES:
            raise SourceError(f"You already have {MAX_FILES} files. Delete one first.")
        sid = c.execute("insert into sources (user_id, filename, bytes, n_chunks) "
                        "values (%s, %s, %s, %s) returning id",
                        (user_id, name, len(raw), len(chunks))).fetchone()["id"]
        with c.cursor() as cur:
            cur.executemany("insert into chunks (user_id, source_id, idx, text) "
                            "values (%s, %s, %s, %s)",
                            [(user_id, sid, i, t) for i, t in enumerate(chunks)])
    return sid


def extract_facts(texts: list[str], known: list[str], user_id: str | None = None) -> list[FileFact]:
    payload = {"known_facts": known[-60:], "excerpts": texts}
    r = llm.complete(name="extract-file-facts", schema=FileFacts, user_id=user_id,
                     max_tokens=1500, temperature=0, messages=[
                         {"role": "system", "content": prompt("c4_ingest")},
                         {"role": "user", "content": to_json(payload)}])
    return r.parsed.facts


def step(user_id: str, source_id: int) -> dict:
    """Process the next BATCH*PARALLEL chunks of one file. Returns the source row."""
    with connection() as c:
        src = c.execute("select * from sources where user_id = %s and id = %s",
                        (user_id, source_id)).fetchone()
        if not src or src["status"] != "reading":
            return src
        rows = c.execute("select id, idx, text from chunks where source_id = %s and idx >= %s "
                         "order by idx limit %s",
                         (source_id, src["n_processed"], BATCH * PARALLEL)).fetchall()
        known = [r["text"] for r in c.execute(
            "select text from facts where user_id = %s order by id", (user_id,)).fetchall()]
    if not rows:
        return _finish(user_id, source_id)
    try:
        vectors = embed([r["text"] for r in rows], user_id)
        batches = [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]
        with llm.trace("ingest-file-step", input={"file": src["filename"], "from": rows[0]["idx"]},
                       user_id=user_id, tags=["ingest"]):
            with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
                found = list(pool.map(lambda b: llm.call_in_context(
                    extract_facts, [r["text"] for r in b], known, user_id)(), batches))
    except llm.LLMError as e:
        return _fail(user_id, source_id, f"The AI could not read part of the file: {e}")
    with connection() as c:
        with c.cursor() as cur:
            cur.executemany("update chunks set embedding = %s::vector where id = %s",
                            [(_vec(v), r["id"]) for r, v in zip(rows, vectors, strict=True)])
        from app import tidy
        seen = [{"text": k} for k in known]
        for facts in found:
            for f in facts:
                if tidy.near_duplicate(f.text, seen):
                    continue
                seen.append({"text": f.text})
                c.execute("insert into facts (user_id, category, text, source, status, source_id, "
                          "quote) values (%s, %s, %s, 'file', 'proposed', %s, %s)",
                          (user_id, f.category, f.text[:300], source_id, f.quote[:300]))
        src = c.execute("update sources set n_processed = n_processed + %s where id = %s "
                        "and user_id = %s returning *", (len(rows), source_id, user_id)).fetchone()
    llm.langfuse.flush()
    if src["n_processed"] >= src["n_chunks"]:
        return _finish(user_id, source_id)
    return src


def _finish(user_id: str, source_id: int) -> dict:
    with connection() as c:
        return c.execute("update sources set status = 'done' where id = %s and user_id = %s "
                         "returning *", (source_id, user_id)).fetchone()


def _fail(user_id: str, source_id: int, error: str) -> dict:
    with connection() as c:
        return c.execute("update sources set status = 'error', error = %s where id = %s "
                         "and user_id = %s returning *",
                         (error[:300], source_id, user_id)).fetchone()


def list_sources(user_id: str) -> list[dict]:
    with connection() as c:
        return c.execute(
            """select s.*, (select count(*) from facts f where f.source_id = s.id
                            and f.status <> 'proposed') as n_facts,
                           (select count(*) from facts f where f.source_id = s.id
                            and f.status = 'proposed') as n_proposed
               from sources s where s.user_id = %s order by s.id""", (user_id,)).fetchall()


def delete_source(user_id: str, source_id: int) -> None:
    with connection() as c:
        c.execute("delete from sources where id = %s and user_id = %s", (source_id, user_id))


def proposed_facts(user_id: str) -> list[dict]:
    with connection() as c:
        return c.execute(
            """select f.*, s.filename from facts f join sources s on s.id = f.source_id
               where f.user_id = %s and f.status = 'proposed' order by f.category, f.id""",
            (user_id,)).fetchall()


def review_facts(user_id: str, keep_ids: set[int]) -> int:
    """Confirmed proposals become active facts; the rest are dropped."""
    with connection() as c:
        rows = c.execute("select id from facts where user_id = %s and status = 'proposed'",
                         (user_id,)).fetchall()
        keep = [r["id"] for r in rows if r["id"] in keep_ids]
        drop = [r["id"] for r in rows if r["id"] not in keep_ids]
        if keep:
            c.execute("update facts set status = 'active' where user_id = %s and id = any(%s)",
                      (user_id, keep))
        if drop:
            c.execute("delete from facts where user_id = %s and id = any(%s)", (user_id, drop))
    return len(keep)
