from types import SimpleNamespace
from django.test import SimpleTestCase
from fundamentals.models import BaseData, MAX_SLUG_ATTEMPTS


class SharedSlugLengthTests(SimpleTestCase):
    def generate(self, base, existing=(), length=64):
        target = SimpleNamespace(
            _meta=SimpleNamespace(get_field=lambda name: SimpleNamespace(max_length=length)),
            slug_exists=lambda slug: slug in existing,
        )
        return BaseData._build_unique_slug(target, base)

    def test_short_slugs_are_unchanged(self):
        self.assertEqual(self.generate("the-quiet-city"), "the-quiet-city")
        self.assertEqual(self.generate("same", {"same", "same-2"}), "same-3")

    def test_long_base_and_suffix_fit_the_model_field(self):
        self.assertEqual(self.generate("a" * 255), "a" * 64)
        self.assertEqual(self.generate("a" * 255, {"a" * 64}), "a" * 62 + "-2")
        occupied = {"a" * 64} | {"a" * 62 + f"-{n}" for n in range(2, 10)}
        self.assertEqual(self.generate("a" * 255, occupied), "a" * 61 + "-10")

    def test_uses_each_models_limit_and_avoids_trailing_hyphen(self):
        self.assertEqual(self.generate("abcd-efgh", length=5), "abcd")
        self.assertEqual(self.generate("a" * 30, length=12), "a" * 12)

    def test_existing_attempt_limit_is_preserved(self):
        target = SimpleNamespace(
            _meta=SimpleNamespace(get_field=lambda name: SimpleNamespace(max_length=64)),
            slug_exists=lambda slug: True,
        )
        with self.assertRaises(ValueError):
            BaseData._build_unique_slug(target, "same")
