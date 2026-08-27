import copy
import importlib
import unittest


def face(family="Editorial Serif", src="/assets/example.com/fonts/editorial.woff2", **descriptors):
    return {"family": family, "src": src, **descriptors}


class PublicFontProjectionTest(unittest.TestCase):
    def setUp(self):
        self.handler = importlib.import_module("lambda_function")

    def project(self, fonts):
        return self.handler._public_site_config({
            "site": {"appIdentity": {"name": "Example"}, "fonts": fonts},
        })["site"]

    def test_four_approved_faces_survive_without_mutating_the_source(self):
        fonts = [
            face("Newsreader", "/assets/example.com/fonts/newsreader-400.woff2", weight="400", style="normal"),
            face("Newsreader", "/assets/example.com/fonts/newsreader-500.woff2", weight="500", style="normal"),
            face("Open Sans", "/assets/example.com/fonts/open-sans-400.woff2", weight="400", style="normal"),
            face("Open Sans", "/assets/example.com/fonts/open-sans-600.woff2", weight="600", style="normal"),
        ]
        original = copy.deepcopy(fonts)
        public = self.project(fonts)
        self.assertEqual(public.get("fonts"), fonts)
        self.assertEqual(public["appIdentity"], {"name": "Example"})
        self.assertEqual(fonts, original)
        self.assertIsNot(public["fonts"], fonts)
        self.assertIsNot(public["fonts"][0], fonts[0])

    def test_empty_and_absent_fonts_preserve_legacy_behavior(self):
        self.assertEqual(self.project([]).get("fonts"), [])
        self.assertEqual(self.handler._public_site_config({"site": {"fonts": []}}),
                         {"site": {"fonts": []}})
        self.assertEqual(self.handler._public_site_config({"site": {"theme": {"mode": "light"}}}),
                         {"site": {"theme": {"mode": "light"}}})
        self.assertEqual(self.handler._public_site_config({}), {})

    def test_optional_descriptors_and_public_https_sources_are_preserved_exactly(self):
        fonts = [face(src="https://cdn.example.com/fonts/editorial.woff2")]
        self.assertEqual(self.project(fonts).get("fonts"), fonts)

    def test_eight_distinct_faces_and_nonoverlapping_ranges_are_supported(self):
        fonts = [face(f"Editorial {index}", weight="1 1000") for index in range(8)]
        self.assertEqual(self.project(fonts).get("fonts"), fonts)
        variants = [face(weight="1 399"), face(weight="400 600"), face(weight="601 1000"),
                    face(weight="1 1000", style="italic")]
        self.assertEqual(self.project(variants).get("fonts"), variants)

    def test_invalid_collections_are_omitted_not_truncated(self):
        for invalid in (None, False, 3, "fonts", {}, [None], [False], [[]], [face()] * 9):
            with self.subTest(value_type=type(invalid).__name__):
                self.assertNotIn("fonts", self.project(invalid))

    def test_font_family_names_are_bounded_ascii_without_css_syntax(self):
        for family in (None, 10, "", " Serif", "Serif ", "Serif\n", "A" * 81,
                       "Nin\u0303a", "Serif, sans-serif", "Serif; color: red", "--Serif", "Two  Spaces"):
            with self.subTest(family=family):
                self.assertNotIn("fonts", self.project([face(family=family)]))
        for family in ("A", "A" * 80, "Open Sans", "Editorial-Serif 2"):
            with self.subTest(valid_family=family):
                self.assertEqual(self.project([face(family=family)]).get("fonts"), [face(family=family)])

    def test_sources_reject_nonfiles_credentials_queries_and_traversal(self):
        invalid_sources = (
            None, 42, "", "fonts/editorial.woff2", "//cdn.example.com/font.woff2",
            "http://cdn.example.com/font.woff2", "data:font/woff2;base64,AAAA",
            "javascript:alert(1)", "https://user:password@cdn.example.com/font.woff2",
            "https://cdn.example.com:443/font.woff2", "/font.css", "/font.woff2?download=1",
            "/font.woff2#fragment", "/font.woff2?X-Amz-Signature=must-not-render",
            "/../font.woff2", "/a/./font.woff2", "/a/../font.woff2", "/%2e%2e/font.woff2",
            "/a\\font.woff2", "/a b/font.woff2", "/font.woff2\n", "/a\x00/font.woff2",
            "/" + "a" * 2048 + ".woff2",
        )
        for source in invalid_sources:
            with self.subTest(source=source):
                self.assertNotIn("fonts", self.project([face(src=source)]))

    def test_weights_and_styles_follow_the_shared_descriptor_contract(self):
        for weight in (None, 400, False, "", "0", "1001", "0400", " 400", "400 ",
                       "400\n", "normal", "700 400", "100 200 300"):
            with self.subTest(weight=weight):
                self.assertNotIn("fonts", self.project([face(weight=weight)]))
        for style in (None, False, "", "oblique", "Normal", "italic "):
            with self.subTest(style=style):
                self.assertNotIn("fonts", self.project([face(style=style)]))
        for weight in ("1", "1000", "1 1000", "400 400"):
            with self.subTest(valid_weight=weight):
                self.assertEqual(self.project([face(weight=weight)]).get("fonts"), [face(weight=weight)])

    def test_source_length_limit_is_inclusive(self):
        source = "/" + "a" * 2041 + ".woff2"
        self.assertEqual(len(source), 2048)
        self.assertEqual(self.project([face(src=source)]).get("fonts"), [face(src=source)])
        self.assertNotIn("fonts", self.project([face(src="/a" + source[1:])]))

    def test_existing_sensitive_value_filter_still_rejects_valid_font_syntax(self):
        for blocked in (face(src="/fonts/X-Amz-Signature.woff2"),
                        face(family="X-Amz-Signature")):
            with self.subTest(blocked=blocked):
                self.assertNotIn("fonts", self.project([face("Safe Serif"), blocked]))

    def test_unknown_and_private_fields_do_not_open_a_public_output_channel(self):
        for key in ("display", "unicodeRange", "privateData", "token", "credentialRef", "headers"):
            with self.subTest(field=key):
                self.assertNotIn("fonts", self.project([face(**{key: "must-not-render"})]))
        for required in ("family", "src"):
            incomplete = face()
            del incomplete[required]
            with self.subTest(missing=required):
                self.assertNotIn("fonts", self.project([incomplete]))

    def test_overlapping_weights_reject_the_whole_list_using_case_insensitive_families(self):
        for fonts in ([face(), face(weight="400", style="normal")],
                      [face(weight="300 500"), face(family="editorial serif", weight="500 700")]):
            with self.subTest(fonts=fonts):
                self.assertNotIn("fonts", self.project(fonts))


if __name__ == "__main__":
    unittest.main()
