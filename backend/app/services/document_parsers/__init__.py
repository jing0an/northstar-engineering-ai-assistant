"""Unified document parser interfaces and extension registry."""

from .base import DocumentParser, normalize_extension
from .parsers import DocxParser, MdParser, PptxParser, TxtParser, XlsxParser
from .legacy import DocParser, PptParser, XlsParser
from .pdf_enhanced import PageQuality, assess_page_quality, extract_pages_enhanced, sort_text_spans
from .document_conversion import (
    ConversionUnavailableError, ConversionTimeoutError, DocumentConversionError,
    LibreOfficeConversionService, UnsupportedLegacyFormatError,
)
from .registry import (
    NotImplementedDocumentParser,
    ParserNotImplemented,
    ParserRegistrationError,
    ParserRegistry,
    PdfDocumentParser,
    UnsupportedDocumentType,
    create_default_registry,
    default_registry,
)

__all__ = [
    "DocumentParser",
    "normalize_extension",
    "NotImplementedDocumentParser",
    "ParserNotImplemented",
    "ParserRegistrationError",
    "ParserRegistry",
    "PdfDocumentParser",
    "UnsupportedDocumentType",
    "create_default_registry",
    "default_registry",
    "TxtParser",
    "MdParser",
    "DocxParser",
    "PptxParser",
    "XlsxParser",
    "DocParser",
    "PptParser",
    "XlsParser",
    "LibreOfficeConversionService",
    "DocumentConversionError",
    "ConversionUnavailableError",
    "ConversionTimeoutError",
    "UnsupportedLegacyFormatError",
    "PageQuality",
    "assess_page_quality",
    "extract_pages_enhanced",
    "sort_text_spans",
]