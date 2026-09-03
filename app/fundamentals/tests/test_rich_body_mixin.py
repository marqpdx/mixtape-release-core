from django.test import SimpleTestCase

from utils.writing.writing_utils import extract_text_from_prosemirror


def _make_doc(*texts):
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": t}]}
            for t in texts
        ],
    }


def _apply_mixin_save_logic(obj):
    """Mirror of RichBodyMixin.save() pre-super() logic for unit testing."""
    if obj.body_json and not obj.body_text:
        obj.body_text = extract_text_from_prosemirror(obj.body_json) or ""


class _Obj:
    def __init__(self, body_json=None, body_text=""):
        self.body_json = body_json if body_json is not None else {}
        self.body_text = body_text


class RichBodyMixinLogicTest(SimpleTestCase):
    def test_body_text_populated_when_empty(self):
        obj = _Obj(body_json=_make_doc("Hello world"))
        _apply_mixin_save_logic(obj)
        self.assertIn("Hello", obj.body_text)

    def test_body_text_not_overwritten_when_already_set(self):
        obj = _Obj(body_json=_make_doc("Hello world"), body_text="Custom text")
        _apply_mixin_save_logic(obj)
        self.assertEqual(obj.body_text, "Custom text")

    def test_empty_body_json_leaves_body_text_empty(self):
        obj = _Obj(body_json={})
        _apply_mixin_save_logic(obj)
        self.assertEqual(obj.body_text, "")

    def test_default_body_json_leaves_body_text_empty(self):
        obj = _Obj()
        _apply_mixin_save_logic(obj)
        self.assertEqual(obj.body_text, "")
