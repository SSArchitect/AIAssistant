from __future__ import annotations

import base64
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agent.documents import parse_document
from agent.main import app, lifespan
from agent.schemas.document import DocumentParseRequest


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "AGENT_MEMORY_STORAGE_PATH",
        str(tmp_path / "agent_memory.json"),
    )
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


def _zip_document(entries: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode("ascii"))
        payload.extend(obj)
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(payload)


def _request(name: str, data: bytes, mime_type: str = "") -> DocumentParseRequest:
    return DocumentParseRequest(
        name=name,
        mime_type=mime_type,
        data_base64=base64.b64encode(data).decode("ascii"),
    )


def test_parse_pdf_extracts_page_text():
    result = parse_document(_request("brief.pdf", _minimal_pdf("Hello PDF")))

    assert result.supported is True
    assert result.format == "pdf"
    assert result.parser == "pypdf"
    assert "# Page 1" in result.text
    assert "Hello PDF" in result.text
    assert result.metadata["page_count"] == 1


def test_parse_docx_extracts_paragraphs():
    data = _zip_document(
        {
            "word/document.xml": """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body>
                    <w:p><w:r><w:t>Quarterly review</w:t></w:r></w:p>
                    <w:p><w:r><w:t>Revenue grew 18 percent.</w:t></w:r></w:p>
                  </w:body>
                </w:document>
            """,
        }
    )

    result = parse_document(_request("review.docx", data))

    assert result.supported is True
    assert result.format == "docx"
    assert "Quarterly review" in result.text
    assert "Revenue grew 18 percent." in result.text
    assert result.metadata["paragraph_count"] == 2


def test_parse_pptx_extracts_slides_in_numeric_order():
    slide = """
        <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
               xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
          <p:cSld><p:spTree><p:sp><p:txBody>
            <a:p><a:r><a:t>{text}</a:t></a:r></a:p>
          </p:txBody></p:sp></p:spTree></p:cSld>
        </p:sld>
    """
    data = _zip_document(
        {
            "ppt/slides/slide10.xml": slide.format(text="Tenth slide"),
            "ppt/slides/slide2.xml": slide.format(text="Second slide"),
        }
    )

    result = parse_document(_request("deck.pptx", data))

    assert result.supported is True
    assert result.format == "pptx"
    assert result.text.index("Second slide") < result.text.index("Tenth slide")
    assert result.metadata["slide_count"] == 2


def test_parse_xlsx_extracts_shared_inline_and_formula_cells():
    data = _zip_document(
        {
            "xl/workbook.xml": """
                <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
                  <sheets><sheet name="Metrics" sheetId="1" r:id="rId1"/></sheets>
                </workbook>
            """,
            "xl/_rels/workbook.xml.rels": """
                <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
                  <Relationship Id="rId1" Target="worksheets/sheet1.xml"
                    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>
                </Relationships>
            """,
            "xl/sharedStrings.xml": """
                <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                  <si><t>Revenue</t></si>
                </sst>
            """,
            "xl/worksheets/sheet1.xml": """
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                  <sheetData>
                    <row r="1">
                      <c r="A1" t="s"><v>0</v></c>
                      <c r="B1" t="inlineStr"><is><t>Q2</t></is></c>
                    </row>
                    <row r="2">
                      <c r="A2"><f>SUM(B2:B3)</f><v>42</v></c>
                    </row>
                  </sheetData>
                </worksheet>
            """,
        }
    )

    result = parse_document(_request("metrics.xlsx", data))

    assert result.supported is True
    assert result.format == "xlsx"
    assert "# Sheet: Metrics" in result.text
    assert "Revenue\tQ2" in result.text
    assert "=SUM(B2:B3) → 42" in result.text
    assert result.metadata["cell_count"] == 3


def test_parse_unsupported_document_returns_capability_result():
    result = parse_document(_request("archive.zip", _zip_document({"note.txt": "hello"})))

    assert result.supported is False
    assert result.parser == ""
    assert "Unsupported document format" in result.warnings[0]


@pytest.mark.asyncio
async def test_document_parse_endpoint(client):
    data = _zip_document(
        {
            "word/document.xml": """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body><w:p><w:r><w:t>Endpoint text</w:t></w:r></w:p></w:body>
                </w:document>
            """,
        }
    )
    response = await client.post(
        "/agent/documents/parse",
        json={
            "name": "endpoint.docx",
            "data_base64": base64.b64encode(data).decode("ascii"),
        },
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Endpoint text"
