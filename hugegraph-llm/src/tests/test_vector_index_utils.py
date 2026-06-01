from types import SimpleNamespace

import gradio as gr
import pytest

from hugegraph_llm.utils.vector_index_utils import read_documents


def _build_pdf(content_stream: bytes) -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Length "
            + str(len(content_stream)).encode()
            + b" >>\nstream\n"
            + content_stream
            + b"\nendstream"
        ),
    ]

    pdf = b"%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode()
        pdf += obj + b"\nendobj\n"

    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n".encode()

    pdf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return pdf


def test_read_documents_reads_txt_file(tmp_path):
    txt_path = tmp_path / "sample.txt"
    txt_path.write_text("hello hugegraph", encoding="utf-8")

    result = read_documents([SimpleNamespace(name=str(txt_path))], "")

    assert result == ["hello hugegraph"]


def test_read_documents_reads_pdf_file(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(
        _build_pdf(b"BT /F1 24 Tf 100 700 Td (Hello HugeGraph PDF) Tj ET")
    )

    result = read_documents([SimpleNamespace(name=str(pdf_path))], "")

    assert "Hello HugeGraph PDF" in result[0]


def test_read_documents_rejects_pdf_without_extractable_text(tmp_path):
    pdf_path = tmp_path / "empty.pdf"
    pdf_path.write_bytes(_build_pdf(b""))

    with pytest.raises(gr.Error, match="No extractable text"):
        read_documents([SimpleNamespace(name=str(pdf_path))], "")
