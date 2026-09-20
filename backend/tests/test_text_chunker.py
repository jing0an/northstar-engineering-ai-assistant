import unittest

from app.services.text_chunker import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    chunk_text,
)


class TextChunkerTest(unittest.TestCase):
    def test_short_text_produces_one_chunk(self) -> None:
        self.assertEqual(chunk_text("简短的项目说明"), ["简短的项目说明"])

    def test_long_text_produces_multiple_chunks(self) -> None:
        chunks = chunk_text("项目进度说明。" * 20, chunk_size=40, chunk_overlap=8)
        self.assertGreater(len(chunks), 1)

    def test_chunk_order_is_preserved(self) -> None:
        text = "第一段内容。\n第二段内容。\n第三段内容。"
        chunks = chunk_text(text, chunk_size=12, chunk_overlap=2)
        positions = [text.find(chunk.replace(" ", "")) for chunk in chunks]
        self.assertTrue(all(position >= 0 for position in positions))
        self.assertEqual(positions, sorted(positions))

    def test_no_empty_chunks_are_created(self) -> None:
        chunks = chunk_text("  第一段  \n\n 第二段 \n", chunk_size=5, chunk_overlap=1)
        self.assertTrue(chunks)
        self.assertTrue(all(chunk.strip() for chunk in chunks))

    def test_overlap_is_applied(self) -> None:
        text = "0123456789" * 8
        chunks = chunk_text(text, chunk_size=20, chunk_overlap=5)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0][-5:], chunks[1][:5])

    def test_empty_and_whitespace_text_returns_empty_list(self) -> None:
        self.assertEqual(chunk_text(""), [])
        self.assertEqual(chunk_text(" \n\t "), [])

    def test_invalid_sizes_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            chunk_text("text", chunk_size=0)
        with self.assertRaises(ValueError):
            chunk_text("text", chunk_size=10, chunk_overlap=-1)
        with self.assertRaises(ValueError):
            chunk_text("text", chunk_size=10, chunk_overlap=10)

    def test_chinese_text_prefers_sentence_boundaries(self) -> None:
        chunks = chunk_text("项目进度正常。当前阶段为施工图设计。计划按期交付。" * 3, chunk_size=25, chunk_overlap=3)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks[:-1]:
            self.assertIn(chunk[-1], "。！？；!?;.!?")

    def test_oversized_single_paragraph_is_split(self) -> None:
        text = "无标点的超长项目说明" * 100
        chunks = chunk_text(text, chunk_size=50, chunk_overlap=5)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= 50 for chunk in chunks))

    def test_defaults_are_positive_and_overlap_is_smaller(self) -> None:
        self.assertGreater(DEFAULT_CHUNK_SIZE, 0)
        self.assertGreaterEqual(DEFAULT_CHUNK_OVERLAP, 0)
        self.assertLess(DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE)


if __name__ == "__main__":
    unittest.main()
