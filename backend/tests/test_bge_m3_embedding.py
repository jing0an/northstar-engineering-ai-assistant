import unittest
from unittest.mock import Mock

from app.services.embedding import BGEM3EmbeddingProvider, DEFAULT_BGE_M3_MODEL


class BgeM3EmbeddingTest(unittest.TestCase):
    def test_model_name_and_loading_are_lazy(self) -> None:
        provider = BGEM3EmbeddingProvider()
        self.assertEqual(provider.model, DEFAULT_BGE_M3_MODEL)
        self.assertIsNone(provider.dimension)
        self.assertIsNone(provider._model)

    def test_single_embedding_uses_injected_model(self) -> None:
        model = Mock()
        model.get_sentence_embedding_dimension.return_value = 3
        model.encode.return_value = [[0.1, 0.2, 0.3]]
        provider = BGEM3EmbeddingProvider(model=model, device="cpu")

        vector = provider.embed_text("项目进度")

        self.assertEqual(vector, [[0.1, 0.2, 0.3]][0])
        self.assertEqual(provider.dimension, 3)
        model.encode.assert_called_once()
        self.assertEqual(model.encode.call_args.kwargs["normalize_embeddings"], True)

    def test_batch_embedding_preserves_count_and_dimension(self) -> None:
        model = Mock()
        model.get_sentence_embedding_dimension.return_value = 2
        model.encode.return_value = [[1, 2], [3, 4]]
        provider = BGEM3EmbeddingProvider(model=model)

        vectors = provider.embed_texts(["进度", "风险"])

        self.assertEqual(vectors, [[1.0, 2.0], [3.0, 4.0]])
        self.assertEqual(provider.dimension, 2)

    def test_empty_batch_does_not_load_model(self) -> None:
        provider = BGEM3EmbeddingProvider()
        self.assertEqual(provider.embed_texts([]), [])
        self.assertIsNone(provider._model)

    def test_empty_and_blank_text_are_rejected(self) -> None:
        model = Mock()
        model.get_sentence_embedding_dimension.return_value = None
        provider = BGEM3EmbeddingProvider(model=model)
        with self.assertRaises(ValueError):
            provider.embed_text("")
        with self.assertRaises(ValueError):
            provider.embed_text(" \n\t ")

    def test_invalid_batch_input_is_rejected(self) -> None:
        model = Mock()
        model.get_sentence_embedding_dimension.return_value = None
        provider = BGEM3EmbeddingProvider(model=model)
        with self.assertRaises(TypeError):
            provider.embed_texts("text")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            provider.embed_text(123)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            provider.embed_texts(["valid", " "])

    def test_model_dimension_is_taken_from_actual_output(self) -> None:
        model = Mock()
        model.get_sentence_embedding_dimension.return_value = None
        model.encode.return_value = [[0.0, 0.5, 1.0, -1.0]]
        provider = BGEM3EmbeddingProvider(model=model)
        provider.embed_text("文本")
        self.assertEqual(provider.dimension, 4)

    def test_inconsistent_model_output_is_rejected(self) -> None:
        model = Mock()
        model.get_sentence_embedding_dimension.return_value = 2
        model.encode.return_value = [[0.1, 0.2], [0.3]]
        provider = BGEM3EmbeddingProvider(model=model)
        with self.assertRaises(ValueError):
            provider.embed_texts(["a", "b"])

    def test_invalid_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BGEM3EmbeddingProvider(model_name=" ")
        with self.assertRaises(TypeError):
            BGEM3EmbeddingProvider(normalize_embeddings="yes")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
