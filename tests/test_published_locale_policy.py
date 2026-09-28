"""Opt-in published-localization contract; all storage is fixture-owned."""
import copy
import importlib
import unittest
from unittest.mock import patch

import test_handler


STRICT_HUB = {
    "hubId": "thehairnarrative-com-journal",
    "ownerDraftDomain": "thehairnarrative.com",
    "source": "primary",
    "routeBasePath": "/the-journal",
    "listPath": "/the-journal",
    "articlePathPattern": "/the-journal/:seriesSlug/:articleSlug",
    "defaultLocale": "en",
    "locales": ["en", "es"],
    "canonicalMode": "owner-canonical",
    "localePolicy": "published-only",
    "publicArticles": [],
}


def localization(locale):
    series = "bridal-forms" if locale == "en" else "formas-nupciales"
    path = f"/the-journal/{series}/synthetic"
    return {
        "title": f"Synthetic {locale}", "summary": f"Summary {locale}",
        "path": path, "categorySlug": series,
        "publishedAt": "2026-09-01T00:00:00Z", "updatedAt": "2026-09-07T00:00:00Z",
        "canonicalPath": path, "robots": "index,follow",
        "imageSrc": f"/features/content-hub-v2/public-media/synthetic/{locale}/r1/cover/w768",
        "imageAlt": f"Synthetic cover {locale}",
    }


def article(locale="es"):
    localized = localization(locale)
    return {
        "pk": f"HUB#{STRICT_HUB['hubId']}", "sk": "ARTICLE#synthetic",
        "articleId": "synthetic", "locale": locale, "status": "published",
        "visibility": "public", **localized, "localizations": {locale: localized},
        "publishedBundleKey": f"content-hubs/test/{STRICT_HUB['hubId']}/published/thehairnarrative.com/{locale}/synthetic/r1/bundle.json",
    }


class PublishedLocalePolicyTest(unittest.TestCase):
    def setUp(self):
        self.runtime = importlib.reload(importlib.import_module("lambda_function"))

    def test_absent_translation_is_not_inferred_from_requested_locale(self):
        for published, requested in (("es", "en"), ("en", "es")):
            with self.subTest(published=published):
                self.assertIsNone(self.runtime._content_hub_article_summary(article(published), STRICT_HUB, requested))

    def test_empty_authored_series_stays_readable_only_in_its_locale_without_affecting_legacy(self):
        taxonomy=[{'taxonomyId':'series-'+lang,'kind':'category','locale':lang,'slug':slug,'label':slug,'path':'/the-journal/'+slug,'visible':True}
            for lang,slug in [('en','bridal-forms'),('es','formas-nupciales')]]
        strict={**STRICT_HUB,'publicTaxonomy':taxonomy}
        legacy={key:value for key,value in strict.items() if key!='localePolicy'}
        for binding in ['', 'fixture-table']:
            with patch.object(self.runtime,'_content_hub_table_name',return_value=binding),patch.object(self.runtime,'_query_content_hub_metadata',return_value=[]):
                result=self.runtime._merge_content_hub_runtime_indexes({'runtime':{'contentHubs':[strict,legacy]}},'en','test')
            one,two=result['runtime']['contentHubs']
            self.assertEqual(one['publicTaxonomy'],taxonomy[:1])
            self.assertEqual(two['publicTaxonomy'],taxonomy)
            selected={'runtime':{'contentHubs':[one]}}
            self.assertTrue(self.runtime._content_hub_public_taxonomy_exists(selected,'/the-journal/bridal-forms'))
            self.assertFalse(self.runtime._content_hub_public_taxonomy_exists(selected,'/the-journal/formas-nupciales'))

    def test_both_published_localizations_are_independent_and_input_is_unchanged(self):
        item = article()
        item["localizations"]["en"] = localization("en")
        before = copy.deepcopy(item)
        for locale in ("en", "es"):
            result = self.runtime._content_hub_article_summary(item, STRICT_HUB, locale)
            for field in ("title", "summary", "path", "publishedAt", "imageSrc", "imageAlt"):
                self.assertEqual(result[field], localization(locale)[field])
            self.assertEqual(result["locale"], locale)
        self.assertEqual(item, before)

    def test_missing_or_malformed_localization_never_falls_back_to_top_level(self):
        for invalid in (None, {}, [], "published", False):
            with self.subTest(invalid=invalid):
                item = article()
                item["localizations"]["en"] = invalid
                self.assertIsNone(self.runtime._content_hub_article_summary(item, STRICT_HUB, "en"))

    def test_required_localized_fields_cannot_be_borrowed_from_another_language(self):
        for field in ("title", "path", "publishedAt"):
            with self.subTest(field=field):
                item = article()
                item["localizations"]["en"] = localization("en")
                del item["localizations"]["en"][field]
                self.assertIsNone(self.runtime._content_hub_article_summary(item, STRICT_HUB, "en"))

    def test_optional_localized_fields_do_not_borrow_top_level_media_or_body(self):
        item = article()
        item["articleContent"] = {"html": "<p>Top-level language only</p>"}
        item["localizations"]["en"] = {key: value for key, value in localization("en").items()
            if key in {"title", "path", "publishedAt"}}
        result = self.runtime._content_hub_article_summary(item, STRICT_HUB, "en")
        for field in ("summary", "updatedAt", "imageSrc", "articleContent"):
            self.assertNotIn(field, result)
        self.assertEqual(result["canonicalPath"], localization("en")["path"])

    def test_opt_in_does_not_expose_draft_or_non_public_records(self):
        for field, value in (("status", "draft"), ("visibility", "private"), ("visibility", "unlisted")):
            item = article()
            item[field] = value
            self.assertIsNone(self.runtime._content_hub_article_summary(item, STRICT_HUB, "es"))

    def test_legacy_hub_retains_existing_fallback_and_primary_locale_behavior(self):
        item = article()
        legacy = {key: value for key, value in STRICT_HUB.items() if key != "localePolicy"}
        result = self.runtime._content_hub_article_summary(item, legacy, "en")
        self.assertEqual(result["title"], localization("es")["title"])
        item["primaryLocale"] = "es"
        self.assertIsNone(self.runtime._content_hub_article_summary(item, legacy, "en"))

    def test_unknown_policy_fails_instead_of_silently_enabling_legacy_fallback(self):
        for value in (None, True, False, [], {}, "", "published", " published-only "):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.runtime._content_hub_article_summary(article(), {**STRICT_HUB, "localePolicy": value}, "en")

    def test_opt_in_survives_public_projection_without_exposing_private_fields(self):
        hub = {**STRICT_HUB, "serverPolicy": {"internal": "never-public"}}
        projected = self.runtime._public_site_config({"runtime": {"contentHubs": [hub]}})
        public = projected["runtime"]["contentHubs"][0]
        self.assertEqual(public.get("localePolicy"), "published-only")
        self.assertNotIn("serverPolicy", public)

    def test_strict_index_cannot_resurrect_authored_static_fallback_articles(self):
        hub = {**STRICT_HUB, "publicArticles": [article()]}
        source = {"runtime": {"contentHubs": [hub]}}
        before = copy.deepcopy(source)
        with patch.object(self.runtime, "_content_hub_table_name", return_value="fixture-table"), \
             patch.object(self.runtime, "_query_content_hub_metadata", return_value=[article()]):
            result = self.runtime._merge_content_hub_runtime_indexes(source, "en", "test")
        self.assertEqual(result["runtime"]["contentHubs"][0]["publicArticles"], [])
        self.assertEqual(source, before)

    def test_mixed_hubs_keep_non_opted_in_behavior_in_the_same_request(self):
        legacy = {key: value for key, value in STRICT_HUB.items() if key != "localePolicy"}
        legacy["hubId"] = "legacy-hub"
        with patch.object(self.runtime, "_content_hub_table_name", return_value="fixture-table"), \
             patch.object(self.runtime, "_query_content_hub_metadata", return_value=[article()]):
            result = self.runtime._merge_content_hub_runtime_indexes(
                {"runtime": {"contentHubs": [STRICT_HUB, legacy]}}, "en", "test")
        strict_result, legacy_result = result["runtime"]["contentHubs"]
        self.assertEqual(strict_result["publicArticles"], [])
        self.assertEqual(legacy_result["publicArticles"][0]["title"], localization("es")["title"])

    def test_missing_metadata_binding_cannot_reenable_static_locale_fallback(self):
        strict = {**STRICT_HUB, "publicArticles": [article()]}
        legacy = {key: value for key, value in strict.items() if key != "localePolicy"}
        legacy["hubId"] = "legacy-hub"
        source = {"runtime": {"contentHubs": [strict, legacy]}}
        before = copy.deepcopy(source)
        with patch.object(self.runtime, "_content_hub_table_name", return_value=""), \
             patch.object(self.runtime, "get_table", side_effect=AssertionError("no cloud binding")):
            result = self.runtime._merge_content_hub_runtime_indexes(source, "en", "test")
        self.assertEqual(result["runtime"]["contentHubs"][0]["publicArticles"], [])
        self.assertEqual(result["runtime"]["contentHubs"][1], legacy)
        self.assertEqual(source, before)

    def test_stale_detail_index_cannot_read_an_unpublished_locale_bundle(self):
        item = article()
        config = {"domain": "thehairnarrative.com", "runtime": {
            "contentHubs": [{**STRICT_HUB, "publicArticles": [item]}]}}
        with patch.object(self.runtime, "_content_hub_table_name", return_value="fixture-table"), \
             patch.object(self.runtime, "_content_hub_packages_bucket_name", return_value="fixture-bucket"), \
             patch.object(self.runtime, "_load_content_hub_article_metadata", return_value=item), \
             patch.object(self.runtime, "_load_content_hub_slug_pointer", side_effect=AssertionError("no missing-locale pointer")), \
             patch.object(self.runtime, "_load_content_hub_json_bundle", side_effect=AssertionError("no missing-locale bundle")):
            self.assertIsNone(self.runtime._content_hub_bundle_for_path(config, item["path"], "en", "test"))


class PublishedLocaleHandlerTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_handler.RuntimeHandlerTest()
        self.fixture.setUp()
        self.runtime = self.fixture.handler
        self.runtime.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.runtime.CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST = "content-hub-packages-test"
        domain = "thehairnarrative.com"
        self.fixture.items[(f"SITE#{domain}", "METADATA")] = {
            "domain": domain, "lifecycle": {"status": "active"},
            "publishedEnvironments": {"test": {"versionId": "test-v1", "prefix": "test-prefix"}},
        }
        self.fixture.put_site("test-prefix", domain, include_not_found=True)
        self.fixture.put_page("test-prefix", domain, "default", "Home")
        self.fixture.put_page("test-prefix", domain, "journal", "Journal")
        self.fixture.put_page("test-prefix", domain, "article", "Article")
        self.fixture.put_page("test-prefix", domain, "not-found", "Not found")
        self.site = self.fixture.payloads[f"test-prefix/{domain}/site-config.json"]
        self.site["site"] = {"i18n": {"defaultLanguage": "en", "supportedLanguages": ["en", "es"]}}
        self.site["runtime"] = {"contentHubs": [copy.deepcopy(STRICT_HUB)]}
        self.site["routes"] += [
            {"path": "/the-journal", "pageId": "journal"},
            {"path": STRICT_HUB["articlePathPattern"], "pageId": "article"},
        ]
        self.fixture.content_hub_items = [article()]

    def read(self, path, lang):
        response = self.runtime.lambda_handler(test_handler.event(
            "api.example.test", path=path, lang=lang, domain="thehairnarrative.com", environment="test"),
            test_handler.Context())
        self.assertEqual(response["statusCode"], 200)
        return test_handler.parse(response)

    def test_home_and_journal_omit_a_never_published_translation(self):
        for path in ("/", "/the-journal"):
            for locale, count in (("en", 0), ("es", 1)):
                with self.subTest(path=path, locale=locale):
                    response = self.read(path, locale)
                    self.assertEqual(len(response["siteConfig"]["runtime"]["contentHubs"][0]["publicArticles"]), count)

    def test_wrong_locale_article_is_404_and_never_reads_its_bundle(self):
        response = self.read(localization("es")["path"], "en")
        self.assertEqual(response["metadata"]["statusCode"], 404)
        self.assertNotIn(article()["publishedBundleKey"], self.fixture.loaded_keys)

    def test_selected_locale_article_remains_readable(self):
        response = self.read(localization("es")["path"], "es")
        self.assertEqual(response["metadata"]["statusCode"], 200)
        self.assertEqual(response["pageId"], "article")


if __name__ == "__main__":
    unittest.main()
