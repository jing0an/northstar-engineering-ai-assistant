import unittest

from app.services.embedding import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingRecord,
    FakeEmbeddingProvider,
)


class EmbeddingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = FakeEmbeddingProvider()

    def test_single_text_embedding(self) -> None:
        vector = self.provider.embed_text("施工图设计阶段")
        self.assertIsInstance(vector, list)
        self.assertEqual(len(vector), DEFAULT_EMBEDDING_DIMENSION)
        self.assertTrue(all(isinstance(value, float) for value in vector))

    def test_batch_embedding_preserves_count(self) -> None:
        vectors = self.provider.embed_texts(["项目进度", "项目风险", "项目成本"])
        self.assertEqual(len(vectors), 3)
        self.assertTrue(all(len(vector) == self.provider.dimension for vector in vectors))

    def test_same_text_is_deterministic(self) -> None:
        self.assertEqual(self.provider.embed_text("相同文本"), self.provider.embed_text("相同文本"))

    def test_different_texts_produce_different_vectors(self) -> None:
        self.assertNotEqual(self.provider.embed_text("文本 A"), self.provider.embed_text("文本 B"))

    def test_dimension_is_fixed(self) -> None:
        self.assertEqual(self.provider.dimension, DEFAULT_EMBEDDING_DIMENSION)
        self.assertEqual(len(self.provider.embed_text("a")), len(self.provider.embed_text("a longer text")))

    def test_empty_text_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.provider.embed_text("")

    def test_blank_text_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.provider.embed_text(" \n\t ")

    def test_empty_batch_returns_empty_list(self) -> None:
        self.assertEqual(self.provider.embed_texts([]), [])

    def test_invalid_inputs_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            self.provider.embed_text(123)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            self.provider.embed_texts("text")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            self.provider.embed_texts(["valid", "  "])

    def test_embedding_record_contains_source_and_metadata(self) -> None:
        text = "项目说明"
        vector = self.provider.embed_text(text)
        record = EmbeddingRecord(
            text=text,
            embedding=vector,
            model=self.provider.model,
            dimension=self.provider.dimension,
        )
        self.assertEqual(record.text, text)
        self.assertEqual(record.model, DEFAULT_EMBEDDING_MODEL)
        self.assertEqual(record.dimension, len(record.embedding))

    def test_invalid_provider_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            FakeEmbeddingProvider(dimension=0)
        with self.assertRaises(ValueError):
            FakeEmbeddingProvider(model=" ")


if __name__ == "__main__":
    unittest.main()
