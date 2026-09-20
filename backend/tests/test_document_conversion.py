import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.document_parsers import (
    ConversionTimeoutError,
    ConversionUnavailableError,
    DocParser,
    DocumentConversionError,
    LibreOfficeConversionService,
    PptParser,
    XlsParser,
)


class FakeModernParser:
    def __init__(self):
        self.paths = []

    def parse(self, file_path, file_type=None):
        self.paths.append(Path(file_path))
        return [{"page_number": 1, "text": "converted"}]


class FakeConverter:
    def __init__(self, converted_path):
        self.converted_path = converted_path

    def convert(self, source):
        from contextlib import contextmanager

        @contextmanager
        def manager():
            yield self.converted_path

        return manager()


class DocumentConversionTest(unittest.TestCase):
    def test_target_extension_mapping(self) -> None:
        service = LibreOfficeConversionService()
        self.assertEqual(service.target_extension("report.DOC"), ".docx")
        self.assertEqual(service.target_extension("slides.ppt"), ".pptx")
        self.assertEqual(service.target_extension("book.xls"), ".xlsx")
        with self.assertRaises(DocumentConversionError):
            service.target_extension("notes.txt")

    def test_missing_libreoffice_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "中文 文件.doc"
            source.write_bytes(b"legacy")
            service = LibreOfficeConversionService()
            with patch.object(service, "find_executable", return_value=None):
                with self.assertRaises(ConversionUnavailableError):
                    with service.convert(source):
                        pass

    def test_conversion_timeout_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "report.doc"
            source.write_bytes(b"legacy")
            service = LibreOfficeConversionService(executable="soffice", timeout_seconds=1)
            with patch("app.services.document_parsers.document_conversion.subprocess.run", side_effect=subprocess.TimeoutExpired("soffice", 1)):
                with self.assertRaises(ConversionTimeoutError):
                    with service.convert(source):
                        pass

    def test_conversion_failure_does_not_expose_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "report.xls"
            source.write_bytes(b"legacy")
            service = LibreOfficeConversionService(executable="soffice")
            completed = subprocess.CompletedProcess([], 1, stdout="ok", stderr="secret stderr")
            with patch("app.services.document_parsers.document_conversion.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(DocumentConversionError, "文档转换失败") as caught:
                    with service.convert(source):
                        pass
            self.assertNotIn("secret stderr", str(caught.exception))

    def test_output_is_temporary_and_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "名字 (v1).ppt"
            source.write_bytes(b"legacy")
            service = LibreOfficeConversionService(executable="soffice")
            captured = {}

            def fake_run(command, **kwargs):
                output_dir = Path(command[command.index("--outdir") + 1])
                output = output_dir / f"{source.stem}.pptx"
                output.write_bytes(b"converted")
                captured["output"] = output
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with patch("app.services.document_parsers.document_conversion.subprocess.run", side_effect=fake_run):
                with service.convert(source) as converted:
                    self.assertTrue(converted.is_file())
                    self.assertNotEqual(converted.parent, source.parent)
            self.assertFalse(captured["output"].exists())
            self.assertEqual(source.read_bytes(), b"legacy")

    def test_legacy_parsers_delegate_to_modern_parsers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            converted = Path(directory) / "converted.docx"
            converted.write_bytes(b"converted")
            for parser_type, extension in ((DocParser, ".doc"), (PptParser, ".ppt"), (XlsParser, ".xls")):
                modern = FakeModernParser()
                parser = parser_type(FakeConverter(converted))
                parser.modern_parser = modern
                result = parser.parse(Path(directory) / f"source{extension}")
                self.assertEqual(result[0]["text"], "converted")
                self.assertEqual(modern.paths, [converted])


if __name__ == "__main__":
    unittest.main()