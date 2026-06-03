# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from types import SimpleNamespace

import gradio as gr
import pytest
from docx import Document

from hugegraph_llm.utils import vector_index_utils
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
        (b"<< /Length " + str(len(content_stream)).encode() + b" >>\nstream\n" + content_stream + b"\nendstream"),
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

    pdf += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n").encode()
    return pdf


def test_read_documents_reads_txt_file(tmp_path):
    txt_path = tmp_path / "sample.txt"
    txt_path.write_text("hello hugegraph", encoding="utf-8")

    result = read_documents([SimpleNamespace(name=str(txt_path))], "")

    assert result == ["hello hugegraph"]


def test_read_documents_reads_pdf_file(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(_build_pdf(b"BT /F1 24 Tf 100 700 Td (Hello HugeGraph PDF) Tj ET"))

    result = read_documents([SimpleNamespace(name=str(pdf_path))], "")

    assert "Hello HugeGraph PDF" in result[0]


def test_read_documents_reads_mixed_case_pdf_file(tmp_path):
    pdf_path = tmp_path / "sample.PDF"
    pdf_path.write_bytes(_build_pdf(b"BT /F1 24 Tf 100 700 Td (Mixed Case PDF) Tj ET"))

    result = read_documents([SimpleNamespace(name=str(pdf_path))], "")

    assert "Mixed Case PDF" in result[0]


def test_read_documents_rejects_pdf_without_extractable_text(tmp_path):
    pdf_path = tmp_path / "empty.pdf"
    pdf_path.write_bytes(_build_pdf(b""))

    with pytest.raises(gr.Error, match="No extractable text"):
        read_documents([SimpleNamespace(name=str(pdf_path))], "")


class BrokenPdfReader:
    def __init__(self, _):
        raise ValueError("broken pdf")


def test_read_documents_reads_docx_file(tmp_path):
    docx_path = tmp_path / "sample.docx"
    document = Document()
    document.add_paragraph("hello docx")
    document.save(docx_path)

    result = read_documents([SimpleNamespace(name=str(docx_path))], "")

    assert "hello docx" in result[0]


def test_read_documents_returns_clear_error_for_unreadable_pdf(monkeypatch, tmp_path):
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"not a valid pdf")

    monkeypatch.setattr(vector_index_utils, "PdfReader", BrokenPdfReader)

    with pytest.raises(gr.Error, match="Failed to read PDF file"):
        read_documents([SimpleNamespace(name=str(pdf_path))], "")


class EncryptedPdfReader:
    is_encrypted = True

    def __init__(self, _):
        self.pages = []


def test_read_documents_returns_clear_error_for_encrypted_pdf(monkeypatch, tmp_path):
    pdf_path = tmp_path / "encrypted.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(vector_index_utils, "PdfReader", EncryptedPdfReader)

    with pytest.raises(gr.Error, match="Encrypted PDF files are not supported"):
        read_documents([SimpleNamespace(name=str(pdf_path))], "")


def test_read_documents_rejects_unsupported_file_type(tmp_path):
    markdown_path = tmp_path / "sample.md"
    markdown_path.write_text("hello markdown", encoding="utf-8")

    with pytest.raises(gr.Error, match="Please input txt, docx, or pdf file"):
        read_documents([SimpleNamespace(name=str(markdown_path))], "")
