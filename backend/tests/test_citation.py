import unittest

from app.services.citation import build_citations
from app.services.document_resolver import DocumentCandidate
from app.services.page_range import DocumentPageMapping
from app.services.vector_store.models import VectorSearchResult


class CitationTest(unittest.TestCase):
    def result(self, chunk, filename="工程.pdf", version=2, page=5, file_id="file-v2", project="project-a", chunk_index=0):
        return VectorSearchResult(
            chunk_id=chunk,
            project_id=project,
            file_id=file_id,
            text=chunk,
            score=0.9,
            metadata={
                "original_filename": filename,
                "document_version": version,
                "page_number": page,
                "chunk_index": chunk_index,
            },
        )

    def test_builds_deduplicated_sorted_citations(self):
        results = [
            self.result("b", page=6, chunk_index=3),
            self.result("a", page=5, chunk_index=1),
            self.result("c", page=5, chunk_index=2),
            self.result("d", filename="A.pdf", version=1, page=2, file_id="a-v1"),
        ]
        citations = build_citations(results)
        self.assertEqual(
            [(item.original_filename, item.document_version, item.page_number) for item in citations],
            [("A.pdf", 1, 2), ("工程.pdf", 2, 5), ("工程.pdf", 2, 6)],
        )

    def test_missing_page_number_does_not_guess(self):
        citation = build_citations([self.result("a", page=None)])[0]
        self.assertEqual(citation.original_filename, "工程.pdf")
        self.assertEqual(citation.document_version, 2)
        self.assertIsNone(citation.page_number)

    def test_expected_resolved_document_rejects_mismatched_results(self):
        expected = DocumentCandidate(
            file_id="file-v2", project_id="project-a", original_filename="工程.pdf",
            document_version=2, is_current=True, uploaded_at="2026-09-02T00:00:00+00:00",
        )
        mismatched = [
            self.result("v1", version=1, file_id="file-v1", page=1),
            self.result("other", version=2, file_id="file-other", page=2),
        ]
        self.assertEqual(build_citations(mismatched, expected), [])

    def test_public_citation_has_no_internal_identifiers(self):
        data = build_citations([self.result("a")])[0].model_dump()
        for forbidden in ("file_id", "chunk_id", "project_id", "score"):
            self.assertNotIn(forbidden, data)

    def test_display_page_mapping_hides_physical_page_numbers(self):
        mapping = DocumentPageMapping({1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10})
        citations = build_citations(
            [self.result("physical-9", page=9), self.result("physical-10", page=10)],
            page_mapping=mapping,
        )
        self.assertEqual([item.page_number for item in citations], [8, 9])

if __name__ == "__main__":
    unittest.main()
