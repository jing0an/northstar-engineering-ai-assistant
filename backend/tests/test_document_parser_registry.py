import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.document_parsers import (
    DocumentParser,
    NotImplementedDocumentParser,
    ParserNotImplemented,
    ParserRegistrationError,
    ParserRegistry,
    PdfDocumentParser,
    UnsupportedDocumentType,
    create_default_registry,
    normalize_extension,
)


class FakeParser(DocumentParser):
    supported_extensions = frozenset({".fake"})

    def parse(self, file_path, file_type=None):
        return [{"page_number": 1, "text": "fake"}]


class DocumentParserRegistryTest(unittest.TestCase):
    def test_normalize_extension(self) -> None:
        self.assertEqual(normalize_extension(".PDF"), ".pdf")
        self.assertEqual(normalize_extension("test.Pdf"), ".pdf")
        self.assertEqual(normalize_extension("test.docx"), ".docx")
        self.assertEqual(normalize_extension(Path("notes.TXT")), ".txt")
        self.assertEqual(normalize_extension("README"), "")

    def test_register_and_find_parser(self) -> None:
        registry = ParserRegistry()
        parser = FakeParser()
        self.assertIs(registry.register(parser), parser)
        self.assertIs(registry.find(".FAKE"), parser)
        self.assertIs(registry.find("report.fake"), parser)

    def test_duplicate_registration_is_rejected(self) -> None:
        registry = ParserRegistry()
        registry.register(FakeParser())
        with self.assertRaises(ParserRegistrationError):
            registry.register(FakeParser())

    def test_default_registry_uses_existing_pdf_parser(self) -> None:
        registry = create_default_registry()
        parser = registry.require(".PDF")
        self.assertIsInstance(parser, PdfDocumentParser)
        self.assertEqual(registry.status(".pdf"), "implemented")

    def test_pdf_adapter_delegates_to_existing_page_parser(self) -> None:
        parser = PdfDocumentParser()
        expected = [{"page_number": 1, "text": "existing PDF parser output"}]
        with patch(
            "app.services.document_parsers.registry.extract_pages",
            return_value=expected,
        ) as extract_pages:
            self.assertEqual(parser.parse("plans.pdf"), expected)
        extract_pages.assert_called_once_with("plans.pdf", "pdf")
    def test_legacy_formats_require_conversion_when_unavailable(self) -> None:
        registry = create_default_registry()
        for extension in (".doc", ".ppt", ".xls"):
            self.assertEqual(registry.status(extension), "conversion_unavailable")
            self.assertIsNotNone(registry.find(extension))
            with self.assertRaises(ParserNotImplemented):
                registry.require(extension)

    def test_registered_formats_are_explicitly_not_implemented(self) -> None:
        registry = create_default_registry()
        for extension in (
            ".rtf",
        ):
            self.assertEqual(registry.status(extension), "not_implemented")
            self.assertIsNotNone(registry.find(extension))
            with self.assertRaises(ParserNotImplemented):
                registry.require(extension)

    def test_unknown_format_is_unsupported(self) -> None:
        registry = create_default_registry()
        self.assertEqual(registry.status(".csv"), "unsupported")
        self.assertIsNone(registry.find(".csv"))
        with self.assertRaises(UnsupportedDocumentType):
            registry.require(".csv")
        self.assertEqual(registry.status("README"), "unsupported")

    def test_not_implemented_parser_does_not_parse(self) -> None:
        parser = NotImplementedDocumentParser(".docx")
        with self.assertRaises(ParserNotImplemented):
            parser.parse("anything.docx")


if __name__ == "__main__":
    unittest.main()