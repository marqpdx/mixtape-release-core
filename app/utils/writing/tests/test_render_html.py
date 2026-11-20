from django.test import SimpleTestCase

from utils.writing.writing_utils import (
    count_words_in_prosemirror,
    extract_text_from_prosemirror,
    render_html_from_prosemirror,
)


def doc(*nodes):
    return {"type": "doc", "content": list(nodes)}


def para(*children):
    return {"type": "paragraph", "content": list(children)}


def text(t, marks=None):
    node = {"type": "text", "text": t}
    if marks:
        node["marks"] = marks
    return node


def mark(kind, **attrs):
    m = {"type": kind}
    if attrs:
        m["attrs"] = attrs
    return m


class RenderHtmlTest(SimpleTestCase):
    def test_empty_dict(self):
        self.assertEqual(render_html_from_prosemirror({}), "")

    def test_none(self):
        self.assertEqual(render_html_from_prosemirror(None), "")

    def test_single_paragraph(self):
        result = render_html_from_prosemirror(doc(para(text("Hello"))))
        self.assertEqual(result, "<p>Hello</p>")

    def test_heading_level_2(self):
        node = {"type": "heading", "attrs": {"level": 2}, "content": [text("Title")]}
        self.assertEqual(render_html_from_prosemirror(doc(node)), "<h2>Title</h2>")

    def test_bold_mark(self):
        result = render_html_from_prosemirror(doc(para(text("bold", [mark("bold")]))))
        self.assertEqual(result, "<p><strong>bold</strong></p>")

    def test_italic_mark(self):
        result = render_html_from_prosemirror(doc(para(text("em", [mark("italic")]))))
        self.assertEqual(result, "<p><em>em</em></p>")

    def test_link_mark(self):
        result = render_html_from_prosemirror(
            doc(para(text("click", [mark("link", href="https://example.com")])))
        )
        self.assertEqual(result, '<p><a href="https://example.com">click</a></p>')

    def test_bullet_list(self):
        li = lambda t: {"type": "listItem", "content": [para(text(t))]}
        node = {"type": "bulletList", "content": [li("A"), li("B")]}
        result = render_html_from_prosemirror(doc(node))
        self.assertEqual(result, "<ul><li><p>A</p></li><li><p>B</p></li></ul>")

    def test_ordered_list(self):
        li = {"type": "listItem", "content": [para(text("one"))]}
        node = {"type": "orderedList", "content": [li]}
        result = render_html_from_prosemirror(doc(node))
        self.assertEqual(result, "<ol><li><p>one</p></li></ol>")

    def test_blockquote(self):
        node = {"type": "blockquote", "content": [para(text("quote"))]}
        result = render_html_from_prosemirror(doc(node))
        self.assertEqual(result, "<blockquote><p>quote</p></blockquote>")

    def test_code_block(self):
        node = {"type": "codeBlock", "content": [text("x = 1")]}
        result = render_html_from_prosemirror(doc(node))
        self.assertEqual(result, "<pre><code>x = 1</code></pre>")

    def test_html_special_chars_escaped(self):
        result = render_html_from_prosemirror(doc(para(text("<b> & \"quotes\""))))
        self.assertEqual(result, "<p>&lt;b&gt; &amp; &quot;quotes&quot;</p>")

    def test_nested_bold_italic(self):
        t = text("both", [mark("bold"), mark("italic")])
        result = render_html_from_prosemirror(doc(para(t)))
        # Either nesting order is acceptable
        self.assertIn("<strong>", result)
        self.assertIn("<em>", result)
        self.assertIn("both", result)

    def test_horizontal_rule(self):
        node = {"type": "horizontalRule"}
        result = render_html_from_prosemirror(doc(node))
        self.assertEqual(result, "<hr>")

    def test_hard_break(self):
        node = para(text("a"), {"type": "hardBreak"}, text("b"))
        result = render_html_from_prosemirror(doc(node))
        self.assertEqual(result, "<p>a<br>b</p>")


def aside(label, **extra):
    node = {"type": "dialogueAside", "attrs": {"label": label, "request": "asked", "response": "answered"}}
    node.update(extra)
    return node


def circle(hex_value):
    return {"type": "colorCircle", "attrs": {"hex": hex_value}}


class WritingExtrasNodesTest(SimpleTestCase):
    """Inline atoms from the writing toolbar's Ext. row keep their visible words."""

    def test_aside_renders_its_phrase_as_prose(self):
        html = render_html_from_prosemirror(doc(para(text("So "), aside("I asked"), text(", then"))))
        self.assertEqual(html, "<p>So I asked, then</p>")

    def test_aside_phrase_is_escaped_and_keeps_marks(self):
        node = aside("<b>x</b>", marks=[mark("italic")])
        self.assertEqual(render_html_from_prosemirror(doc(para(node))), "<p><em>&lt;b&gt;x&lt;/b&gt;</em></p>")

    def test_aside_exchange_is_not_emitted(self):
        html = render_html_from_prosemirror(doc(para(aside("phrase"))))
        self.assertNotIn("asked", html)
        self.assertNotIn("answered", html)

    def test_aside_phrase_counts_toward_text_and_words(self):
        body = doc(para(text("one"), aside("two three")))
        self.assertIn("two three", extract_text_from_prosemirror(body))
        self.assertEqual(count_words_in_prosemirror(body), 3)

    def test_color_circle_renders_coloured_dot(self):
        html = render_html_from_prosemirror(doc(para(circle("#0B5B2A"))))
        self.assertEqual(html, '<p><span style="color:#0B5B2A" title="#0B5B2A">&#9679;</span></p>')

    def test_color_circle_rejects_anything_but_six_digit_hex(self):
        for bad in ["red", "#0B5", "#0B5B2A;background:url(x)", None]:
            self.assertEqual(render_html_from_prosemirror(doc(para(circle(bad)))), "<p></p>")

