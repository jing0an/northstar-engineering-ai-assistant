"""Parser adapters that convert legacy Office formats before parsing."""

from __future__ import annotations

from pathlib import Path

from .base import DocumentParser
from .document_conversion import LibreOfficeConversionService
from .parsers import DocxParser, PptxParser, XlsxParser


class LegacyOfficeParser(DocumentParser):
    """Delegate legacy parsing to conversion plus an existing modern parser."""

    implemented = LibreOfficeConversionService.is_available()
    conversion_required = True

    def __init__(self, converter: LibreOfficeConversionService | None = None, modern_parser: DocumentParser | None = None) -> None:
        self.converter = converter or LibreOfficeConversionService()
        self.modern_parser = modern_parser

    def parse(self, file_path: str | Path, file_type: str | None = None) -> list[dict[str, object]]:
        with self.converter.convert(file_path) as converted:
            if self.modern_parser is None:
                raise RuntimeError("Legacy parser has no modern parser delegate")
            return self.modern_parser.parse(converted)


class DocParser(LegacyOfficeParser):
    supported_extensions = frozenset({".doc"})

    def __init__(self, converter: LibreOfficeConversionService | None = None) -> None:
        super().__init__(converter, DocxParser())


class PptParser(LegacyOfficeParser):
    supported_extensions = frozenset({".ppt"})

    def __init__(self, converter: LibreOfficeConversionService | None = None) -> None:
        super().__init__(converter, PptxParser())


class XlsParser(LegacyOfficeParser):
    supported_extensions = frozenset({".xls"})

    def __init__(self, converter: LibreOfficeConversionService | None = None) -> None:
        super().__init__(converter, XlsxParser())