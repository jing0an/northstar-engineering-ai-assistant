import tempfile
import unittest
from pathlib import Path

from app.services.document_ingestion import (
    ChunkingError,
    DocumentIngestionService,
    EmbeddingError,
    EmptyDocumentTextError,
    IngestionFileNotFoundError,
    TextExtractionError,
    UnsupportedDocumentTypeError,
    VectorStoreWriteError,
)
from app.services.embedding import FakeEmbeddingProvider


class RecordingVectorStore:
    def __init__(self, error=None):
        self.documents = []
        self.error = error

    def add_documents(self, documents):
        if self.error:
            raise self.error
        self.documents.extend(documents)
        return len(documents)


class DocumentIngestionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.parsed_types = []

        def parser(path, file_type):
            self.parsed_types.append(file_type)
            return "第一段项目内容。\n第二段项目内容。"

        def chunker(text):
            return [part.strip() for part in text.split("\n") if part.strip()]

        self.parser = parser
        self.chunker = chunker
        self.embedding = FakeEmbeddingProvider(dimension=4)
        self.store = RecordingVectorStore()
        self.service = DocumentIngestionService(parser, chunker, self.embedding, self.store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _ingest(self, suffix: str = ".pdf"):
        path = self.root / f"plan{suffix}"
        path.write_bytes(b"test document")
        return self.service.ingest("file-1", "project-a", path, suffix, f"plan{suffix}")

    def _page_service(self, page_parser):
        return DocumentIngestionService(
            self.parser,
            self.chunker,
            self.embedding,
            self.store,
            page_parser=page_parser,
        )

    def test_pdf_ingestion_runs_full_pipeline(self) -> None:
        result = self._ingest(".pdf")
        self.assertEqual(result.chunk_count, 2)
        self.assertEqual(result.vector_count, 2)
        self.assertEqual(result.status, "completed")
        self.assertEqual(self.parsed_types, ["pdf"])

    def test_docx_ingestion_runs_full_pipeline(self) -> None:
        result = self._ingest(".docx")
        self.assertEqual(result.file_id, "file-1")
        self.assertEqual(result.project_id, "project-a")
        self.assertEqual(len(self.store.documents), 2)

    def test_metadata_and_chunk_index_are_correct(self) -> None:
        self._ingest(".pdf")
        first, second = self.store.documents
        self.assertEqual(first.metadata["project_id"], "project-a")
        self.assertEqual(first.metadata["file_id"], "file-1")
        self.assertEqual(first.metadata["original_filename"], "plan.pdf")
        self.assertEqual(first.metadata["file_type"], "pdf")
        self.assertEqual(first.metadata["chunk_index"], 0)
        self.assertEqual(second.metadata["chunk_index"], 1)
        self.assertNotIn("page_number", first.metadata)

    def test_project_and_file_ids_are_passed_and_chunk_ids_are_stable(self) -> None:
        self._ingest(".pdf")
        first_ids = [document.chunk_id for document in self.store.documents]
        self.store.documents.clear()
        self._ingest(".pdf")
        second_ids = [document.chunk_id for document in self.store.documents]
        self.assertEqual(first_ids, second_ids)
        self.assertTrue(all(document.project_id == "project-a" for document in self.store.documents))
        self.assertTrue(all(document.file_id == "file-1" for document in self.store.documents))

    def test_dependencies_are_constructor_injected(self) -> None:
        self.assertIs(self.service.parser, self.parser)
        self.assertIs(self.service.chunker, self.chunker)
        self.assertIs(self.service.embedding_provider, self.embedding)
        self.assertIs(self.service.vector_store, self.store)
        self.assertIsNone(self.service.page_parser)

    def test_page_parser_adds_page_number_to_metadata(self) -> None:
        def page_parser(path, file_type):
            return [
                {"page_number": 1, "text": "第一页内容A。\n第一页内容B。"},
                {"page_number": 2, "text": "第二页内容。"},
            ]

        path = self.root / "pages.pdf"
        path.write_bytes(b"document")
        result = self._page_service(page_parser).ingest(
            "file-1", "project-a", path, "pdf", "pages.pdf"
        )

        self.assertEqual(result.chunk_count, 3)
        self.assertEqual(
            [document.metadata["chunk_index"] for document in self.store.documents],
            [0, 1, 2],
        )
        self.assertEqual(
            [document.metadata["page_number"] for document in self.store.documents],
            [1, 1, 2],
        )

    def test_page_parser_does_not_cross_page_boundaries(self) -> None:
        def page_parser(path, file_type):
            return [
                {"page_number": 1, "text": "first page A\nfirst page B"},
                {"page_number": 2, "text": "second page A\nsecond page B"},
            ]

        path = self.root / "pages.pdf"
        path.write_bytes(b"document")
        self._page_service(page_parser).ingest(
            "file-1", "project-a", path, "pdf", "pages.pdf"
        )

        self.assertEqual(
            [(document.text, document.metadata["page_number"]) for document in self.store.documents],
            [
                ("first page A", 1),
                ("first page B", 1),
                ("second page A", 2),
                ("second page B", 2),
            ],
        )

    def test_page_parser_is_optional(self) -> None:
        self._ingest(".pdf")
        self.assertEqual(len(self.store.documents), 2)
        self.assertTrue(all("page_number" not in item.metadata for item in self.store.documents))

    def test_version_metadata_is_preserved_with_page_metadata(self) -> None:
        path = self.root / "versioned.pdf"
        path.write_bytes(b"document")
        service = self._page_service(
            lambda *_: [{"page_number": 2, "text": "versioned content"}]
        )

        service.ingest(
            "file-1",
            "project-a",
            path,
            "pdf",
            "versioned.pdf",
            document_version=3,
            is_current=True,
            uploaded_at="2026-09-07T00:00:00+00:00",
        )

        metadata = self.store.documents[0].metadata
        self.assertEqual(metadata["document_version"], 3)
        self.assertTrue(metadata["is_current"])
        self.assertEqual(metadata["uploaded_at"], "2026-09-07T00:00:00+00:00")
        self.assertEqual(metadata["page_number"], 2)
        self.assertEqual(metadata["chunk_index"], 0)
    def test_duplicate_metadata_is_preserved_with_page_metadata(self) -> None:
        path = self.root / "duplicate.pdf"
        path.write_bytes(b"document")
        service = self._page_service(
            lambda *_: [{"page_number": 1, "text": "duplicate content"}]
        )
        service.ingest(
            "duplicate-file",
            "project-a",
            path,
            "pdf",
            "duplicate.pdf",
            is_duplicate=True,
            duplicate_of_file_id="original-file",
        )
        metadata = self.store.documents[0].metadata
        self.assertTrue(metadata["is_duplicate"])
        self.assertEqual(metadata["duplicate_of_file_id"], "original-file")

    def test_page_parser_invalid_result_fails_clearly(self) -> None:
        path = self.root / "invalid.pdf"
        path.write_bytes(b"document")
        service = self._page_service(lambda *_: [{"page_number": 1}])

        with self.assertRaises(TextExtractionError):
            service.ingest("file-1", "project-a", path, "pdf", "invalid.pdf")

    def test_all_pages_empty_fails(self) -> None:
        path = self.root / "empty-pages.pdf"
        path.write_bytes(b"document")
        service = self._page_service(
            lambda *_: [
                {"page_number": 1, "text": " "},
                {"page_number": 2, "text": ""},
            ]
        )

        with self.assertRaises(EmptyDocumentTextError):
            service.ingest("file-1", "project-a", path, "pdf", "empty-pages.pdf")

    def test_empty_text_fails_clearly(self) -> None:
        service = DocumentIngestionService(lambda *_: " \n", self.chunker, self.embedding, self.store)
        path = self.root / "empty.pdf"; path.write_bytes(b"empty")
        with self.assertRaises(EmptyDocumentTextError): service.ingest("f", "p", path, "pdf", "empty.pdf")

    def test_missing_file_fails_clearly(self) -> None:
        with self.assertRaises(IngestionFileNotFoundError):
            self.service.ingest("f", "p", self.root / "missing.pdf", "pdf", "missing.pdf")

    def test_unsupported_type_fails_before_parser(self) -> None:
        path = self.root / "plan.txt"; path.write_bytes(b"text")
        with self.assertRaises(UnsupportedDocumentTypeError): self.service.ingest("f", "p", path, "txt", "plan.txt")
        self.assertEqual(self.parsed_types, [])

    def test_embedding_failure_is_wrapped(self) -> None:
        class BrokenEmbedding:
            def embed_texts(self, texts): raise RuntimeError("embedding down")
        path = self.root / "plan.pdf"; path.write_bytes(b"text")
        service = DocumentIngestionService(self.parser, self.chunker, BrokenEmbedding(), self.store)
        with self.assertRaises(EmbeddingError): service.ingest("f", "p", path, "pdf", "plan.pdf")

    def test_vector_store_failure_is_wrapped(self) -> None:
        path = self.root / "plan.pdf"; path.write_bytes(b"text")
        service = DocumentIngestionService(self.parser, self.chunker, self.embedding, RecordingVectorStore(RuntimeError("qdrant down")))
        with self.assertRaises(VectorStoreWriteError): service.ingest("f", "p", path, "pdf", "plan.pdf")

    def test_chunking_failure_is_wrapped(self) -> None:
        path = self.root / "plan.pdf"; path.write_bytes(b"text")
        service = DocumentIngestionService(self.parser, lambda text: (_ for _ in ()).throw(RuntimeError("chunk down")), self.embedding, self.store)
        with self.assertRaises(ChunkingError): service.ingest("f", "p", path, "pdf", "plan.pdf")

    def test_parser_failure_is_wrapped(self) -> None:
        path = self.root / "plan.pdf"; path.write_bytes(b"text")
        service = DocumentIngestionService(lambda *_: (_ for _ in ()).throw(RuntimeError("parser down")), self.chunker, self.embedding, self.store)
        with self.assertRaises(TextExtractionError): service.ingest("f", "p", path, "pdf", "plan.pdf")


if __name__ == "__main__": unittest.main()