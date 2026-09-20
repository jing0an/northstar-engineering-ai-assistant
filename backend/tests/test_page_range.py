import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.page_range import (
    DocumentPageMapping,
    _printed_page_number,
    has_page_range_reference,
    mapping_from_metadata,
    pdf_page_mapping,
    resolve_page_numbers,
)


class FakePage:
    def __init__(self, text: str):
        self.text = text

    def extract_text(self) -> str:
        return self.text


class PageRangeTest(unittest.TestCase):
    @staticmethod
    def mapping_for(*page_texts: str) -> DocumentPageMapping | None:
        reader = type("FakeReader", (), {"pages": [FakePage(text) for text in page_texts]})()
        with patch("pypdf.PdfReader", return_value=reader):
            return pdf_page_mapping("test.pdf")

    def test_last_pages_use_reliable_display_maximum(self):
        self.assertEqual(resolve_page_numbers("最后两页", 9), [8, 9])
        self.assertEqual(resolve_page_numbers("最后一页", 9), [9])
        self.assertEqual(resolve_page_numbers("最后三页", 9), [7, 8, 9])

    def test_explicit_page_forms(self):
        self.assertEqual(resolve_page_numbers("第8页"), [8])
        self.assertEqual(resolve_page_numbers("第8到第9页"), [8, 9])
        self.assertEqual(resolve_page_numbers("第8-9页"), [8, 9])
        self.assertEqual(resolve_page_numbers("第8、9页"), [8, 9])
        self.assertEqual(resolve_page_numbers("第8页和第9页"), [8, 9])

    def test_last_page_requires_document_page_count(self):
        self.assertTrue(has_page_range_reference("最后两页"))
        self.assertIsNone(resolve_page_numbers("最后两页"))

    def test_test_pdf_maps_nine_display_pages_to_ten_physical_pages(self):
        path = Path(__file__).resolve().parents[1] / "storage" / "BJ-KC-2024-01" / "125ddc347dea4ff7b4ed5ecabebc2fd4.pdf"
        mapping = pdf_page_mapping(path)
        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.max_display_page_number, 9)
        self.assertEqual(mapping.to_physical([8]), [9])
        self.assertEqual(mapping.to_physical([9]), [10])
        self.assertEqual(
            mapping.to_physical(resolve_page_numbers("最后两页", mapping.max_display_page_number) or []),
            [9, 10],
        )

    def test_printed_page_number_accepts_header_before_number(self):
        self.assertEqual(_printed_page_number("固定页眉\n1\n正文"), 1)
        self.assertEqual(_printed_page_number("固定页眉\n2\n正文"), 2)

    def test_headered_consecutive_pages_build_mapping(self):
        mapping = self.mapping_for(
            "封面\n无页码",
            "固定页眉\n1\n正文",
            "固定页眉\n2\n正文",
            "固定页眉\n3\n正文",
        )

        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.display_to_physical, {1: 2, 2: 3, 3: 4})

    def test_third_display_page_maps_to_eleventh_physical_page(self):
        preliminary_pages = [f"前置页 {number}\n没有印刷页码" for number in range(1, 9)]
        mapping = self.mapping_for(
            *preliminary_pages,
            "固定页眉\n1\n正文",
            "固定页眉\n2\n正文",
            "固定页眉\n3\n正文",
        )

        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.to_physical([3]), [11])

    def test_body_numbers_outside_top_lines_are_not_page_labels(self):
        text = "固定页眉\n第一章 工程概况\n2024 年项目\n1\n正文内容"
        self.assertIsNone(_printed_page_number(text))

    def test_broken_printed_page_sequence_is_rejected(self):
        mapping = self.mapping_for(
            "固定页眉\n1\n正文",
            "固定页眉\n3\n正文",
        )
        self.assertIsNone(mapping)

    def test_duplicate_printed_page_number_is_rejected(self):
        mapping = self.mapping_for(
            "固定页眉\n1\n正文",
            "固定页眉\n1\n正文",
        )
        self.assertIsNone(mapping)

    def test_printed_page_sequence_must_start_at_one(self):
        mapping = self.mapping_for(
            "固定页眉\n2\n正文",
            "固定页眉\n3\n正文",
        )
        self.assertIsNone(mapping)

    def test_metadata_page_mapping_remains_supported(self):
        mapping = mapping_from_metadata({"display_page_mapping": {"1": 9, "2": 10, "3": 11}})
        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.to_physical([3]), [11])

    def test_unmapped_display_page_is_not_guessed(self):
        mapping = DocumentPageMapping({1: 2, 2: 3})
        self.assertIsNone(mapping.to_physical([3]))


if __name__ == "__main__":
    unittest.main()
