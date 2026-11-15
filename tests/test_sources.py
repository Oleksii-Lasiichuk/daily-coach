import pytest

from app import sources


def test_chunks_cover_text_with_overlap():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(40))
    chunks = sources.chunk_text(text, size=1400, overlap=250)
    assert all(len(c) <= 1400 + 400 for c in chunks)
    assert "Paragraph 0." in chunks[0] and "Paragraph 39." in chunks[-1]
    for a, b in zip(chunks, chunks[1:], strict=False):  # next chunk repeats the tail
        assert a[-60:].split()[-1] in b[:400]


def test_decode_handles_cp1251():
    assert sources.decode("Коліно".encode("cp1251")) == "Коліно"


def test_rejects_wrong_type_and_size(users):
    u = users()
    with pytest.raises(sources.SourceError, match="only .txt, .md and .json"):
        sources.add_source(u.id, "health.pdf", b"x")
    with pytest.raises(sources.SourceError, match="5 MB"):
        sources.add_source(u.id, "big.txt", b"x" * (sources.MAX_BYTES + 1))
    with pytest.raises(sources.SourceError, match="empty"):
        sources.add_source(u.id, "empty.md", b"   ")


def test_review_keeps_only_selected(users):
    from app.db import connection
    u = users()
    sid = sources.add_source(u.id, "a.md", b"some text")
    with connection() as c:
        ids = [c.execute("insert into facts (user_id, category, text, source, status, source_id, "
                         "quote) values (%s, 'health', %s, 'file', 'proposed', %s, 'q') "
                         "returning id", (u.id, t, sid)).fetchone()["id"] for t in ("keep", "drop")]
    assert sources.review_facts(u.id, {ids[0]}) == 1
    from app import store
    assert [f["text"] for f in store.list_facts(u.id)] == ["keep"]
    assert sources.proposed_facts(u.id) == []
