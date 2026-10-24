from app.rag.preprocess import chunk_text, preprocess_page


def test_preprocess_strips_headers_and_page_numbers():
    raw = (
        "Adan Retail — Internal\n"
        "Confidential\n"
        "Returns are accepted within 30 days of delivery for unused items.\n"
        "Page 2 of 4\n"
        "3\n"
    )
    cleaned = preprocess_page("return_policy.pdf", 2, raw)
    assert cleaned is not None
    assert "30 days" in cleaned.text
    assert "Adan Retail — Internal" not in cleaned.text
    assert "Page 2" not in cleaned.text


def test_chunking_respects_size():
    text = "Paragraph one. " * 40 + "\n\n" + "Paragraph two. " * 40
    chunks = chunk_text(text, chunk_size=200, overlap=40)
    assert len(chunks) >= 2
    assert all(len(c) <= 280 for c in chunks)  # allow small overflow from overlap join
