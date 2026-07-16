from __future__ import annotations

import base64
from dataclasses import dataclass, field
from io import BytesIO
import mimetypes
from pathlib import PurePosixPath
import posixpath
import re
from typing import Any, Callable
from urllib.parse import unquote_to_bytes
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from agent.schemas.document import DocumentParseRequest, DocumentParseResponse


MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_ZIP_ENTRIES = 5000
MAX_ZIP_ENTRY_BYTES = 32 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 128 * 1024 * 1024

_PDF_MIME_TYPES = {"application/pdf"}
_DOCX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_PPTX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_XLSX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_SUPPORTED_EXTENSIONS = {"pdf", "docx", "pptx", "xlsx"}

_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


class DocumentParseError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_document"):
        self.code = code
        super().__init__(message)


@dataclass
class _ExtractedDocument:
    text: str
    parser: str
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    title: str = ""


def parse_document(request: DocumentParseRequest) -> DocumentParseResponse:
    data, data_mime = _decode_payload(request)
    document_format = _detect_format(
        request.name,
        request.mime_type or data_mime,
        data,
    )
    if document_format not in _SUPPORTED_EXTENSIONS:
        return DocumentParseResponse(
            supported=False,
            format=document_format,
            title=_filename_title(request.name),
            metadata={"bytes": len(data)},
            warnings=["Unsupported document format. Supported formats: PDF, DOCX, PPTX, XLSX."],
        )

    extractors: dict[str, Callable[[bytes], _ExtractedDocument]] = {
        "pdf": _extract_pdf,
        "docx": _extract_docx,
        "pptx": _extract_pptx,
        "xlsx": _extract_xlsx,
    }
    extracted = extractors[document_format](data)
    normalized = _normalize_document_text(extracted.text)
    text, truncated = _truncate_text(normalized, request.max_chars)
    warnings = list(extracted.warnings)
    if not text:
        if document_format == "pdf":
            warnings.append(
                "No selectable text was extracted. The PDF may be scanned or image-only; OCR is not enabled."
            )
        else:
            warnings.append("No text content was extracted from the document.")
    title = extracted.title or _filename_title(request.name)
    metadata = {
        **extracted.metadata,
        "bytes": len(data),
        "characters": len(text),
        "source_name": request.name,
        "source_mime_type": request.mime_type or data_mime,
    }
    return DocumentParseResponse(
        supported=True,
        format=document_format,
        parser=extracted.parser,
        text=text,
        title=title,
        summary=_summarize_text(text),
        truncated=truncated,
        metadata=metadata,
        warnings=list(dict.fromkeys(warnings)),
    )


def _decode_payload(request: DocumentParseRequest) -> tuple[bytes, str]:
    raw = str(request.data_url or "").strip()
    mime_type = ""
    if raw:
        if not raw.startswith("data:") or "," not in raw:
            raise DocumentParseError("data_url must be a valid data URL")
        header, payload = raw.split(",", 1)
        mime_type = header[5:].split(";", 1)[0].strip().lower()
        try:
            if ";base64" in header.lower():
                data = base64.b64decode(payload, validate=True)
            else:
                data = unquote_to_bytes(payload)
        except (ValueError, TypeError) as exc:
            raise DocumentParseError("invalid data URL payload") from exc
    else:
        payload = "".join(str(request.data_base64 or "").split())
        if not payload:
            raise DocumentParseError("data_base64 or data_url is required")
        try:
            data = base64.b64decode(payload, validate=True)
        except (ValueError, TypeError) as exc:
            raise DocumentParseError("invalid base64 document data") from exc
    if not data:
        raise DocumentParseError("document is empty")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentParseError(
            f"document exceeds {MAX_DOCUMENT_BYTES} bytes",
            code="document_too_large",
        )
    return data, mime_type


def _detect_format(name: str, mime_type: str, data: bytes) -> str:
    extension = PurePosixPath(str(name or "")).suffix.casefold().lstrip(".")
    normalized_mime = str(mime_type or "").split(";", 1)[0].strip().casefold()
    if extension in _SUPPORTED_EXTENSIONS:
        return extension
    if normalized_mime in _PDF_MIME_TYPES or data.startswith(b"%PDF-"):
        return "pdf"
    if normalized_mime in _DOCX_MIME_TYPES:
        return "docx"
    if normalized_mime in _PPTX_MIME_TYPES:
        return "pptx"
    if normalized_mime in _XLSX_MIME_TYPES:
        return "xlsx"
    if data.startswith(b"PK\x03\x04"):
        try:
            with _safe_zip(data) as archive:
                names = set(archive.namelist())
                if "word/document.xml" in names:
                    return "docx"
                if "ppt/presentation.xml" in names or any(
                    name.startswith("ppt/slides/slide") for name in names
                ):
                    return "pptx"
                if "xl/workbook.xml" in names:
                    return "xlsx"
        except DocumentParseError:
            raise
        except Exception:
            return extension
    guessed, _ = mimetypes.guess_type(name)
    if guessed in _PDF_MIME_TYPES:
        return "pdf"
    return extension


def _safe_zip(data: bytes) -> ZipFile:
    try:
        archive = ZipFile(BytesIO(data))
    except BadZipFile as exc:
        raise DocumentParseError("invalid OOXML zip container") from exc
    entries = archive.infolist()
    if len(entries) > MAX_ZIP_ENTRIES:
        archive.close()
        raise DocumentParseError("document archive contains too many entries")
    total_size = 0
    for entry in entries:
        if entry.flag_bits & 0x1:
            archive.close()
            raise DocumentParseError("encrypted OOXML documents are not supported")
        if entry.file_size > MAX_ZIP_ENTRY_BYTES:
            archive.close()
            raise DocumentParseError("document archive entry is too large")
        total_size += entry.file_size
        if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
            archive.close()
            raise DocumentParseError("document archive expands beyond the safety limit")
    return archive


def _read_zip_entry(archive: ZipFile, name: str) -> bytes:
    try:
        payload = archive.read(name)
    except KeyError as exc:
        raise DocumentParseError(f"document is missing required entry: {name}") from exc
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise DocumentParseError("XML entity declarations are not allowed")
    return payload


def _parse_xml(payload: bytes, *, name: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise DocumentParseError(f"invalid XML in {name}") from exc


def _extract_pdf(data: bytes) -> _ExtractedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentParseError(
            "PDF parser dependency is not installed",
            code="parser_unavailable",
        ) from exc
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            if reader.decrypt("") == 0:
                raise DocumentParseError("password-protected PDFs are not supported")
        pages: list[str] = []
        nonempty_pages = 0
        for index, page in enumerate(reader.pages, start=1):
            page_text = str(page.extract_text() or "").strip()
            if page_text:
                nonempty_pages += 1
                pages.append(f"# Page {index}\n{page_text}")
        metadata = reader.metadata or {}
        title = str(getattr(metadata, "title", "") or "").strip()
        return _ExtractedDocument(
            text="\n\n".join(pages),
            parser="pypdf",
            title=title,
            metadata={
                "page_count": len(reader.pages),
                "text_page_count": nonempty_pages,
                "encrypted": bool(reader.is_encrypted),
            },
        )
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError(f"failed to parse PDF: {exc}") from exc


def _extract_docx(data: bytes) -> _ExtractedDocument:
    with _safe_zip(data) as archive:
        names = set(archive.namelist())
        ordered_entries = ["word/document.xml"]
        ordered_entries.extend(
            sorted(
                (
                    name
                    for name in names
                    if re.fullmatch(r"word/header\d+\.xml", name)
                ),
                key=_numeric_sort_key,
            )
        )
        ordered_entries.extend(
            sorted(
                (
                    name
                    for name in names
                    if re.fullmatch(r"word/footer\d+\.xml", name)
                ),
                key=_numeric_sort_key,
            )
        )
        sections: list[str] = []
        paragraph_count = 0
        for entry_name in ordered_entries:
            if entry_name not in names:
                continue
            root = _parse_xml(_read_zip_entry(archive, entry_name), name=entry_name)
            paragraphs = _ooxml_paragraphs(root, _WORD_NS)
            paragraph_count += len(paragraphs)
            if not paragraphs:
                continue
            if entry_name.startswith("word/header"):
                sections.append("[Header]\n" + "\n".join(paragraphs))
            elif entry_name.startswith("word/footer"):
                sections.append("[Footer]\n" + "\n".join(paragraphs))
            else:
                sections.append("\n".join(paragraphs))
        return _ExtractedDocument(
            text="\n\n".join(sections),
            parser="stdlib-docx",
            metadata={"paragraph_count": paragraph_count},
        )


def _extract_pptx(data: bytes) -> _ExtractedDocument:
    with _safe_zip(data) as archive:
        slide_names = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ),
            key=_numeric_sort_key,
        )
        slides: list[str] = []
        text_slide_count = 0
        for index, slide_name in enumerate(slide_names, start=1):
            root = _parse_xml(_read_zip_entry(archive, slide_name), name=slide_name)
            paragraphs = _ooxml_paragraphs(root, _DRAWING_NS)
            if paragraphs:
                text_slide_count += 1
                slides.append(f"# Slide {index}\n" + "\n".join(paragraphs))
        return _ExtractedDocument(
            text="\n\n".join(slides),
            parser="stdlib-pptx",
            metadata={
                "slide_count": len(slide_names),
                "text_slide_count": text_slide_count,
            },
        )


def _extract_xlsx(data: bytes) -> _ExtractedDocument:
    with _safe_zip(data) as archive:
        workbook = _parse_xml(
            _read_zip_entry(archive, "xl/workbook.xml"),
            name="xl/workbook.xml",
        )
        relationships = _xlsx_relationships(archive)
        shared_strings = _xlsx_shared_strings(archive)
        sheet_nodes = workbook.findall(f".//{{{_SHEET_NS}}}sheet")
        rendered_sheets: list[str] = []
        cell_count = 0
        for sheet_index, sheet in enumerate(sheet_nodes, start=1):
            sheet_name = str(sheet.attrib.get("name") or f"Sheet {sheet_index}")
            relationship_id = str(sheet.attrib.get(f"{{{_REL_NS}}}id") or "")
            target = relationships.get(relationship_id)
            if not target:
                continue
            root = _parse_xml(_read_zip_entry(archive, target), name=target)
            rows: list[str] = []
            for row in root.findall(f".//{{{_SHEET_NS}}}row"):
                values: list[tuple[int, str]] = []
                for cell in row.findall(f"{{{_SHEET_NS}}}c"):
                    value = _xlsx_cell_value(cell, shared_strings)
                    if value == "":
                        continue
                    column = _xlsx_column_index(str(cell.attrib.get("r") or ""))
                    values.append((column, value))
                    cell_count += 1
                if not values:
                    continue
                max_column = min(max(column for column, _ in values), 255)
                columns = [""] * (max_column + 1)
                for column, value in values:
                    if 0 <= column <= max_column:
                        columns[column] = value.replace("\t", " ").replace("\n", " ")
                while columns and not columns[-1]:
                    columns.pop()
                rows.append("\t".join(columns))
            if rows:
                rendered_sheets.append(f"# Sheet: {sheet_name}\n" + "\n".join(rows))
        return _ExtractedDocument(
            text="\n\n".join(rendered_sheets),
            parser="stdlib-xlsx",
            metadata={
                "sheet_count": len(sheet_nodes),
                "text_sheet_count": len(rendered_sheets),
                "cell_count": cell_count,
            },
        )


def _ooxml_paragraphs(root: ElementTree.Element, namespace: str) -> list[str]:
    paragraphs: list[str] = []
    for paragraph in root.findall(f".//{{{namespace}}}p"):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{{{namespace}}}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{{{namespace}}}tab":
                parts.append("\t")
            elif node.tag in {f"{{{namespace}}}br", f"{{{namespace}}}cr"}:
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def _xlsx_relationships(archive: ZipFile) -> dict[str, str]:
    entry_name = "xl/_rels/workbook.xml.rels"
    root = _parse_xml(_read_zip_entry(archive, entry_name), name=entry_name)
    relationships: dict[str, str] = {}
    for relationship in root.findall(f".//{{{_PACKAGE_REL_NS}}}Relationship"):
        relationship_id = str(relationship.attrib.get("Id") or "")
        target = str(relationship.attrib.get("Target") or "")
        target_mode = str(relationship.attrib.get("TargetMode") or "")
        if not relationship_id or not target or target_mode.casefold() == "external":
            continue
        normalized = posixpath.normpath(
            target.lstrip("/")
            if target.startswith("/xl/")
            else posixpath.join("xl", target)
        )
        normalized = normalized.lstrip("/")
        if not normalized.startswith("xl/") or normalized.startswith("../"):
            continue
        relationships[relationship_id] = normalized
    return relationships


def _xlsx_shared_strings(archive: ZipFile) -> list[str]:
    entry_name = "xl/sharedStrings.xml"
    if entry_name not in archive.namelist():
        return []
    root = _parse_xml(_read_zip_entry(archive, entry_name), name=entry_name)
    values: list[str] = []
    for item in root.findall(f".//{{{_SHEET_NS}}}si"):
        values.append(
            "".join(
                node.text or ""
                for node in item.iter(f"{{{_SHEET_NS}}}t")
            )
        )
    return values


def _xlsx_cell_value(
    cell: ElementTree.Element,
    shared_strings: list[str],
) -> str:
    cell_type = str(cell.attrib.get("t") or "")
    value_node = cell.find(f"{{{_SHEET_NS}}}v")
    raw_value = str(value_node.text or "") if value_node is not None else ""
    if cell_type == "inlineStr":
        inline = cell.find(f"{{{_SHEET_NS}}}is")
        raw_value = (
            "".join(
                node.text or ""
                for node in inline.iter(f"{{{_SHEET_NS}}}t")
            )
            if inline is not None
            else ""
        )
    elif cell_type == "s":
        try:
            raw_value = shared_strings[int(raw_value)]
        except (ValueError, IndexError):
            raw_value = ""
    elif cell_type == "b":
        raw_value = "TRUE" if raw_value == "1" else "FALSE"
    formula = cell.find(f"{{{_SHEET_NS}}}f")
    formula_text = str(formula.text or "").strip() if formula is not None else ""
    if formula_text:
        return f"={formula_text}" + (f" → {raw_value}" if raw_value else "")
    return raw_value.strip()


def _xlsx_column_index(reference: str) -> int:
    match = re.match(r"([A-Za-z]+)", reference)
    if not match:
        return 0
    value = 0
    for char in match.group(1).upper():
        value = value * 26 + (ord(char) - ord("A") + 1)
    return max(0, value - 1)


def _numeric_sort_key(value: str) -> tuple[int, str]:
    match = re.search(r"(\d+)(?=\.xml$)", value)
    return (int(match.group(1)) if match else 0, value)


def _normalize_document_text(value: str) -> str:
    value = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\x00", "")
    lines = [re.sub(r"[ \t]+$", "", line) for line in value.split("\n")]
    value = "\n".join(lines)
    value = re.sub(r"\n{4,}", "\n\n\n", value)
    return value.strip()


def _truncate_text(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars].rstrip(), True


def _summarize_text(value: str) -> str:
    for paragraph in re.split(r"\n\s*\n", value):
        cleaned = " ".join(paragraph.lstrip("# ").split())
        if cleaned:
            return cleaned[:320]
    return ""


def _filename_title(name: str) -> str:
    filename = PurePosixPath(str(name or "")).name
    if "." in filename:
        filename = filename.rsplit(".", 1)[0]
    return filename.strip()
