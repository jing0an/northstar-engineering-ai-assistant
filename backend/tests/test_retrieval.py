import unittest

from app.services.embedding import FakeEmbeddingProvider
from app.services.retrieval import RetrievalResult, RetrievalService
from app.services.vector_store.models import VectorSearchResult


class InMemoryVectorStore:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    def search(
            self,
            query_embedding,
            top_k=5,
            project_id=None,
            file_id=None,
            original_filename=None,
            document_version=None,
            is_current=None,
    ):
        self.calls.append(
            {
                "query_embedding": query_embedding,
                "top_k": top_k,
                "project_id": project_id,
                "file_id": file_id,
                "original_filename": original_filename,
                "document_version": document_version,
                "is_current": is_current,
            }
        )

        matches = [
            result
            for result in self.results
            if result.project_id == project_id
               and (file_id is None or result.file_id == file_id)
               and (
                       original_filename is None
                       or result.metadata.get("original_filename") == original_filename
               )
               and (
                       document_version is None
                       or result.metadata.get("document_version") == document_version
               )
        ]
        return matches[:top_k]


def result(chunk_id="chunk-1", project_id="project-a", score=0.9):
    return VectorSearchResult(
        chunk_id=chunk_id,
        project_id=project_id,
        file_id="file-1",
        text=f"text for {chunk_id}",
        score=score,
        metadata={"original_filename": "plan.pdf", "chunk_index": 0, "is_current": True},
    )


class RetrievalServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.embedding = FakeEmbeddingProvider(dimension=4)
        self.store = InMemoryVectorStore([result(), result("chunk-2", score=0.8), result("chunk-b", "project-b")])
        self.service = RetrievalService(self.embedding, self.store)

    def test_normal_retrieval_returns_project_results(self) -> None:
        matches = self.service.retrieve("项目进度", "project-a", top_k=2)
        self.assertEqual([match.chunk_id for match in matches], ["chunk-1", "chunk-2"])
        self.assertEqual(len(matches), 2)

    def test_project_isolation_is_passed_to_vector_store(self) -> None:
        matches = self.service.retrieve("项目风险", "project-b")
        self.assertEqual([match.project_id for match in matches], ["project-b"])
        self.assertEqual(self.store.calls[-1]["project_id"], "project-b")

    def test_cross_project_results_are_not_returned(self) -> None:
        class LeakyStore(InMemoryVectorStore):
            def search(
                    self,
                    query_embedding,
                    top_k=5,
                    project_id=None,
                    file_id=None,
                    original_filename=None,
            ):
                self.calls.append(
                    {
                        "query_embedding": query_embedding,
                        "top_k": top_k,
                        "project_id": project_id,
                        "file_id": file_id,
                        "original_filename": original_filename,
                    }
                )
                return self.results

        service = RetrievalService(self.embedding, LeakyStore([result(), result("chunk-b", "project-b")]))
        matches = service.retrieve("查询", "project-a")
        self.assertEqual([match.project_id for match in matches], ["project-a"])

    def test_result_structure_is_preserved(self) -> None:
        match = self.service.retrieve("进度", "project-a")[0]
        self.assertIsInstance(match, RetrievalResult)
        self.assertEqual(match.file_id, "file-1")
        self.assertEqual(match.metadata["original_filename"], "plan.pdf")
        self.assertEqual(match.score, 0.9)

    def test_no_results_returns_empty_list(self) -> None:
        self.assertEqual(self.service.retrieve("不存在", "project-c"), [])

    def test_query_embedding_is_called_and_forwarded(self) -> None:
        class RecordingEmbedding:
            def __init__(self):
                self.queries = []

            def embed_text(self, query):
                self.queries.append(query)
                return [0.1, 0.2]

        embedding = RecordingEmbedding()
        store = InMemoryVectorStore()
        RetrievalService(embedding, store).retrieve("  查询内容  ", "project-a", top_k=3)
        self.assertEqual(embedding.queries, ["查询内容"])
        self.assertEqual(store.calls[0]["query_embedding"], [0.1, 0.2])
        self.assertEqual(store.calls[0]["top_k"], 3)

    def test_is_current_filter_is_forwarded_and_applied(self) -> None:
        historical = VectorSearchResult(
            chunk_id="old",
            project_id="project-a",
            file_id="file-1",
            text="old version",
            score=0.7,
            metadata={"original_filename": "plan.pdf", "is_current": False},
        )
        self.store.results.append(historical)
        matches = self.service.retrieve("进度", "project-a", is_current=True)
        self.assertEqual([match.chunk_id for match in matches], ["chunk-1", "chunk-2"])
        self.assertTrue(self.store.calls[-1]["is_current"])

    def test_is_current_none_disables_version_filter(self) -> None:
        historical = VectorSearchResult(
            chunk_id="old",
            project_id="project-a",
            file_id="file-1",
            text="old version",
            score=0.7,
            metadata={"original_filename": "plan.pdf", "is_current": False},
        )
        self.store.results.append(historical)
        matches = self.service.retrieve("进度", "project-a", is_current=None, top_k=10)
        self.assertIn("old", [match.chunk_id for match in matches])
    def test_file_id_and_document_version_isolate_results(self) -> None:
        results = [
            VectorSearchResult(chunk_id="v1", project_id="project-a", file_id="file-v1", text="融资计划 V1", score=0.9,
                               metadata={"original_filename": "工程.pdf", "document_version": 1, "is_current": False}),
            VectorSearchResult(chunk_id="v2", project_id="project-a", file_id="file-v2", text="融资计划 V2", score=0.9,
                               metadata={"original_filename": "工程.pdf", "document_version": 2, "is_current": False}),
            VectorSearchResult(chunk_id="v3", project_id="project-a", file_id="file-v3", text="融资计划 V3", score=0.9,
                               metadata={"original_filename": "工程.pdf", "document_version": 3, "is_current": True}),
        ]
        store = InMemoryVectorStore(results)
        service = RetrievalService(self.embedding, store)
        matches = service.retrieve("融资计划", "project-a", top_k=10, file_id="file-v2", document_version=2, is_current=False)
        self.assertEqual([item.text for item in matches], ["融资计划 V2"])
        self.assertEqual(store.calls[-1]["file_id"], "file-v2")
        self.assertEqual(store.calls[-1]["document_version"], 2)
    def test_blank_query_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.retrieve("  ", "project-a")

    def test_blank_project_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.retrieve("查询", " ")

    def test_invalid_top_k_is_rejected(self) -> None:
        for top_k in (0, -1, True):
            with self.subTest(top_k=top_k), self.assertRaises(ValueError):
                self.service.retrieve("查询", "project-a", top_k=top_k)


    def test_page_numbers_filter_is_forwarded_and_enforced(self) -> None:
        page_eight = VectorSearchResult(
            chunk_id="page-8", project_id="project-a", file_id="file-1", text="page eight", score=0.9,
            metadata={"original_filename": "plan.pdf", "page_number": 8, "is_current": True},
        )
        page_nine = VectorSearchResult(
            chunk_id="page-9", project_id="project-a", file_id="file-1", text="page nine", score=0.8,
            metadata={"original_filename": "plan.pdf", "page_number": 9, "is_current": True},
        )
        page_seven = VectorSearchResult(
            chunk_id="page-7", project_id="project-a", file_id="file-1", text="page seven", score=0.7,
            metadata={"original_filename": "plan.pdf", "page_number": 7, "is_current": True},
        )
        service = RetrievalService(self.embedding, InMemoryVectorStore([page_eight, page_nine, page_seven]))
        matches = service.retrieve("清单", "project-a", top_k=10, page_numbers=[8, 9])
        self.assertEqual([item.chunk_id for item in matches], ["page-8", "page-9"])

    def test_page_numbers_do_not_fallback_to_entire_document(self) -> None:
        service = RetrievalService(self.embedding, InMemoryVectorStore([result()]))
        self.assertEqual(service.retrieve("清单", "project-a", page_numbers=[9]), [])


if __name__ == "__main__":
    unittest.main()

