from django.test import SimpleTestCase

from writing.search_index import extract_search_text


class SearchTextExtractionTests(SimpleTestCase):
    def test_preserves_inline_words_and_paragraph_breaks(self):
        document = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "A "},
                    {"type": "text", "text": "careful", "marks": [{"type": "bold"}]},
                    {"type": "text", "text": " introduction."},
                ]},
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "Second paragraph."},
                ]},
            ],
        }

        self.assertEqual(
            extract_search_text(document),
            "A careful introduction.\n\nSecond paragraph.",
        )

    def test_handles_nested_blocks_and_invalid_input(self):
        document = {"type": "doc", "content": [{
            "type": "bulletList", "content": [
                {"type": "listItem", "content": [{
                    "type": "paragraph", "content": [{"type": "text", "text": "First"}],
                }]},
                {"type": "listItem", "content": [{
                    "type": "paragraph", "content": [{"type": "text", "text": "Second"}],
                }]},
            ],
        }]}

        self.assertEqual(extract_search_text(document), "First\nSecond")
        self.assertEqual(extract_search_text(None), "")
