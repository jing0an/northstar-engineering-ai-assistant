"""Registry for document parsers keyed by normalized file extension."""

from __future__ import annotations

from pathlib import Path

from app.services.document_parser import extract_pages

from .base import DocumentParser, normalize_extension
from .parsers import DocxParser, MdParser, PptxParser, TxtParser, XlsxParser
from .legacy import DocParser, PptParser, XlsParser
from .pdf_enhanced import extract_pages_enhanced


class UnsupportedDocumentType(LookupError):
    """Raised when no parser is registered for an extension."""


class ParserNotImplemented(LookupError):
    """Raised when an extension is registered but has no implementation yet."""


class ParserRegistrationError(ValueError):
    """Raised when registration would silently replace an existing parser."""


class PdfDocumentParser(DocumentParser):
    """Adapter around the existing PDF page parser."""

    supported_extensions = frozenset({".pdf"})

    def parse(
        self, file_path: str | Path, file_type: str | None = None
    ) -> list[dict[str, object]]:
        return extract_pages_enhanced(file_path, extract_pages)


class NotImplementedDocumentParser(DocumentParser):
    """Explicit registry entry for a future parser implementation."""

    implemented = False

    def __init__(self, extension: str) -> None:
        normalized = normalize_extension(extension)
        if not normalized:
            raise ParserRegistrationError("Parser extensions must be non-empty")
        self.supported_extensions = frozenset({normalized})

    def parse(
        self, file_path: str | Path, file_type: str | None = None
    ) -> list[dict[str, object]]:
        raise ParserNotImplemented(
            f"No parser implementation is available for {next(iter(self.supported_extensions))}"
        )


class ParserRegistry:
    """Map file extensions to parser instances without implicit fallback."""

    def __init__(self) -> None:
        self._parsers: dict[str, DocumentParser] = {}

    def register(self, parser: DocumentParser) -> DocumentParser:
        for extension in parser.supported_extensions:
            normalized = normalize_extension(extension)
            if not normalized:
                raise ParserRegistrationError("Parser extensions must be non-empty")
            if normalized in self._parsers:
                raise ParserRegistrationError(
                    f"A parser is already registered for {normalized}"
                )
        for extension in parser.supported_extensions:
            self._parsers[normalize_extension(extension)] = parser
        return parser

    def find(self, extension_or_path: str | Path) -> DocumentParser | None:
        """Return the registered parser, including not-implemented entries."""
        return self._parsers.get(normalize_extension(extension_or_path))

    def require(self, extension_or_path: str | Path) -> DocumentParser:
        normalized = normalize_extension(extension_or_path)
        parser = self._parsers.get(normalized)
        if parser is None:
            raise UnsupportedDocumentType(
                f"No parser is registered for {normalized or '<unknown>'}"
            )
        if not parser.implemented:
            raise ParserNotImplemented(
                f"Parser for {normalized} is registered but not implemented"
            )
        return parser

    def status(self, extension_or_path: str | Path) -> str:
        """Return ``implemented``, ``not_implemented``, or ``unsupported``."""
        parser = self.find(extension_or_path)
        if parser is None:
            return "unsupported"
        if parser.implemented:
            return "implemented"
        if getattr(parser, "conversion_required", False):
            return "conversion_unavailable"
        return "not_implemented"


def create_default_registry() -> ParserRegistry:
    """Build the A1 registry without changing existing ingestion wiring."""
    registry = ParserRegistry()
    registry.register(PdfDocumentParser())
    for parser in (TxtParser(), MdParser(), DocxParser(), PptxParser(), XlsxParser()):
        registry.register(parser)
    for parser in (DocParser(), PptParser(), XlsParser()):
        registry.register(parser)
    for extension in (".rtf",):
        registry.register(NotImplementedDocumentParser(extension))
    return registry


default_registry = create_default_registry()