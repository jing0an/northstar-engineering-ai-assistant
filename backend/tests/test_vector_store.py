import unittest
from types import SimpleNamespace

from app.services.vector_store import QdrantVectorStore, VectorDocument


class FakeQdrantClient:
    def __init__(self, exists=False, dimension=3):
        self.exists, self.dimension = exists, dimension
        self.created, self.upserts, self.queries, self.deletions = [], [], [], []
        self.payload_updates = []

    def collection_exists(self, name): return self.exists
    def get_collection(self, name):
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=self.dimension))))
    def create_collection(self, **kwargs): self.created.append(kwargs); self.exists = True
    def upsert(self, **kwargs): self.upserts.append(kwargs)
    def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return SimpleNamespace(points=[{"score": 0.9, "payload": {"chunk_id": "chunk-1", "project_id": "project-a", "file_id": "file-1", "original_filename": "plan.pdf", "text": "进度说明"}}])
    def delete(self, **kwargs): self.deletions.append(kwargs)
    def set_payload(self, **kwargs): self.payload_updates.append(kwargs)
    def get_collections(self): return SimpleNamespace(collections=[])


def document(chunk_id="chunk-1", project_id="project-a"):
    return VectorDocument(chunk_id=chunk_id, project_id=project_id, file_id="file-1", text="进度说明", embedding=[0.1, 0.2, 0.3], metadata={"original_filename": "plan.pdf"})


class VectorStoreTest(unittest.TestCase):
    def test_collection_is_created_once(self):
        client = FakeQdrantClient(); QdrantVectorStore(3, client=client)
        self.assertEqual(len(client.created), 1); self.assertEqual(client.created[0]["vectors_config"]["size"], 3)
        QdrantVectorStore(3, client=client); self.assertEqual(len(client.created), 1)

    def test_existing_dimension_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "dimension mismatch"): QdrantVectorStore(4, client=FakeQdrantClient(True, 3))

    def test_add_documents_upserts_stable_points_and_metadata(self):
        client = FakeQdrantClient(); store = QdrantVectorStore(3, client=client)
        self.assertEqual(store.add_documents([document()]), 1); first = client.upserts[0]["points"][0]
        store.add_documents([document()]); second = client.upserts[1]["points"][0]
        self.assertEqual(first["id"], second["id"]); self.assertEqual(first["payload"]["project_id"], "project-a"); self.assertEqual(first["payload"]["original_filename"], "plan.pdf")

    def test_empty_batch_is_a_noop(self):
        client = FakeQdrantClient(); store = QdrantVectorStore(3, client=client)
        self.assertEqual(store.add_documents([]), 0); self.assertEqual(client.upserts, [])

    def test_search_uses_project_filter_and_top_k(self):
        client = FakeQdrantClient(); store = QdrantVectorStore(3, client=client)
        results = store.search([0.1, 0.2, 0.3], top_k=7, project_id="project-a")
        self.assertEqual(results[0].chunk_id, "chunk-1"); self.assertEqual(results[0].score, 0.9)
        query = client.queries[0]; self.assertEqual(query["limit"], 7); self.assertEqual(query["query_filter"]["must"][0]["match"]["value"], "project-a")

    def test_search_current_version_filter(self) -> None:
        client = FakeQdrantClient(); store = QdrantVectorStore(3, client=client)
        store.search([0.1, 0.2, 0.3], project_id="project-a", is_current=True)
        conditions = client.queries[-1]["query_filter"]["must"]
        self.assertEqual(conditions[-1], {"key": "is_current", "match": {"value": True}})

    def test_search_historical_version_filter(self) -> None:
        client = FakeQdrantClient(); store = QdrantVectorStore(3, client=client)
        store.search([0.1, 0.2, 0.3], project_id="project-a", is_current=False)
        conditions = client.queries[-1]["query_filter"]["must"]
        self.assertEqual(conditions[-1], {"key": "is_current", "match": {"value": False}})

    def test_search_none_omits_version_filter(self) -> None:
        client = FakeQdrantClient(); store = QdrantVectorStore(3, client=client)
        store.search([0.1, 0.2, 0.3], project_id="project-a", is_current=None)
        conditions = client.queries[-1]["query_filter"]["must"]
        self.assertFalse(any(condition["key"] == "is_current" for condition in conditions))
    def test_search_combines_file_version_and_current_filters(self):
        client = FakeQdrantClient(); store = QdrantVectorStore(3, client=client)
        store.search([0.1, 0.2, 0.3], project_id="project-a", file_id="file-v2", document_version=2, is_current=True)
        conditions = client.queries[-1]["query_filter"]["must"]
        self.assertEqual({condition["key"] for condition in conditions}, {"project_id", "file_id", "document_version", "is_current"})
        self.assertTrue(all(condition["key"] in {"project_id", "file_id", "document_version", "is_current"} for condition in conditions))
        self.assertEqual(next(c for c in conditions if c["key"] == "file_id")["match"]["value"], "file-v2")
        self.assertEqual(next(c for c in conditions if c["key"] == "document_version")["match"]["value"], 2)
    def test_search_validates_top_k_and_dimension(self):
        store = QdrantVectorStore(3, client=FakeQdrantClient())
        with self.assertRaises(ValueError): store.search([0.1], project_id="project-a")
        with self.assertRaises(ValueError): store.search([0.1, 0.2, 0.3], top_k=0)

    def test_update_file_metadata_targets_only_project_and_file(self):
        client = FakeQdrantClient()
        store = QdrantVectorStore(3, client=client)
        store.update_file_metadata(
            project_id="project-a",
            file_id="file-v1",
            metadata={"document_version": 1, "is_current": False, "is_duplicate": False},
        )
        update = client.payload_updates[0]
        self.assertEqual(update["payload"]["document_version"], 1)
        conditions = update["points"].must
        self.assertEqual(
            {(item.key, item.match.value) for item in conditions},
            {("project_id", "project-a"), ("file_id", "file-v1")},
        )

    def test_delete_supports_chunk_file_and_project(self):
        client = FakeQdrantClient(); store = QdrantVectorStore(3, client=client)
        store.delete(chunk_ids=["chunk-1"], project_id="project-a"); self.assertIn("filter", client.deletions[0]["points_selector"])
        store.delete(file_id="file-1", project_id="project-a"); self.assertEqual(len(client.deletions[1]["points_selector"]["filter"]["must"]), 2)

    def test_delete_requires_a_selector(self):
        with self.assertRaises(ValueError): QdrantVectorStore(3, client=FakeQdrantClient()).delete()

    def test_health_delegates_to_client(self): self.assertTrue(QdrantVectorStore(3, client=FakeQdrantClient()).health())

    def test_search_page_numbers_are_or_conditions_with_document_constraints(self):
        client = FakeQdrantClient()
        store = QdrantVectorStore(3, client=client)
        store.search(
            [0.1, 0.2, 0.3], project_id="project-a", file_id="file-v2",
            document_version=2, is_current=True, page_numbers=[8, 9],
        )
        query_filter = client.queries[-1]["query_filter"]
        self.assertEqual(
            {condition["key"] for condition in query_filter["must"]},
            {"project_id", "file_id", "document_version", "is_current"},
        )
        self.assertEqual(
            [condition["match"]["value"] for condition in query_filter["should"]],
            [8, 9],
        )

if __name__ == "__main__": unittest.main()


