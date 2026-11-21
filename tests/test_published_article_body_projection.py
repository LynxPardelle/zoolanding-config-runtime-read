"""Published article bodies must replace only their matching current-article fallback."""
import copy
import unittest
from unittest.mock import patch

import lambda_function as runtime


DOMAIN = "example.com"
PATH = "/blog/web/body-precedence"
ARTICLE = {
    "articleId": "art_body_precedence", "locale": "es", "primaryLocale": "es",
    "status": "published", "visibility": "public", "title": "Published body",
    "path": PATH, "categorySlug": "web", "publishedAt": "2026-11-01T12:00:00Z",
    "articleContent": {"html": "<p>Old static indexed body</p>"},
}
HUB = {"hubId": "main", "routeBasePath": "/blog", "listPath": "/blog", "articlePathPattern": "/blog/:categorySlug/:articleSlug",
       "defaultLocale": "es", "locales": ["es", "en"], "publicArticles": [ARTICLE]}


def payload(article=None):
    return {"version": 1, "domain": DOMAIN, "pageId": "blog-article", "variables": {
        "articleContent": {"html": "<p>Generic page fallback</p>"},
        "contentHub": {"currentArticle": copy.deepcopy(ARTICLE if article is None else article)},
    }}


def load_published(body, *, bundle_overrides=None, shared=False):
    domain = runtime.SHARED_ZOOSITE_READER if shared else DOMAIN
    owner = runtime.SHARED_ZOOSITE_OWNER if shared else DOMAIN
    hub = {**HUB, **({"hubId": "zoosite-main", "ownerDraftDomain": owner,
                     "source": "authorized", "canonicalMode": "noindex-shared"} if shared else {})}
    config = {"domain": domain, "runtime": {"contentHubs": [copy.deepcopy(hub)]}}
    key = f"content-hubs/prod/{hub['hubId']}/published/{owner}/es/{ARTICLE['articleId']}/rev_1/bundle.json"
    metadata = {**ARTICLE, "publishedBundleKey": key}
    bundle = {"articleId": ARTICLE["articleId"], "locale": "es", "path": PATH, "status": "published",
              "variables": {"articleContent": copy.deepcopy(body)}, **(bundle_overrides or {})}
    before = copy.deepcopy((config, metadata, bundle))
    with patch.object(runtime, "load_item", side_effect=AssertionError("Unexpected live storage read")), patch.object(runtime, "load_json_from_s3", side_effect=AssertionError("Unexpected live storage read")), patch.object(runtime, "_content_hub_table_name", return_value="fixture-table"), patch.object(
        runtime, "_content_hub_packages_bucket_name", return_value="fixture-bucket"
    ), patch.object(runtime, "_load_content_hub_article_metadata", return_value=metadata), patch.object(
        runtime, "_load_content_hub_json_bundle", return_value=bundle
    ):
        published = runtime._content_hub_bundle_for_path(config, PATH, "es", "production")
    assert (config, metadata, bundle) == before, "bundle lookup must not mutate source/cache inputs"
    return published, bundle


class PublishedArticleBodyProjectionTest(unittest.TestCase):
    def test_published_html_replaces_only_current_article_fallback(self):
        body = {"html": "<section><h2>Exact new body</h2><p>Published text.</p></section>"}
        published, _ = load_published(body)
        result = runtime._merge_content_hub_bundle_variables(payload(), published)
        self.assertEqual(result["variables"]["contentHub"]["currentArticle"]["articleContent"], body)
        self.assertEqual(result["variables"]["articleContent"], body)

    def test_published_delta_does_not_inherit_static_html(self):
        body = {"ops": [{"insert": "Published Delta\n", "attributes": {"header": 2}}]}
        published, _ = load_published(body)
        result = runtime._merge_content_hub_bundle_variables(payload(), published)
        current = result["variables"]["contentHub"]["currentArticle"]["articleContent"]
        self.assertEqual(current, body)
        self.assertNotIn("html", current)

    def test_shared_owner_normalization_is_copied_exactly(self):
        body = {"ops": [{"insert": "Contact", "attributes": {"link": "/contacto"}}]}
        published, _ = load_published(body, shared=True)
        effective = published["variables"]["articleContent"]
        self.assertEqual(effective["ops"][0]["attributes"]["link"], "https://zoositioweb.com.mx/contacto")
        result = runtime._merge_content_hub_bundle_variables(payload(), published)
        self.assertEqual(result["variables"]["contentHub"]["currentArticle"]["articleContent"], effective)

    def test_no_package_or_no_package_body_preserves_fallback(self):
        original = payload()
        for published in (None, {}, {"variables": {"other": "published metadata"}}):
            with self.subTest(published=published):
                result = runtime._merge_content_hub_bundle_variables(original, published)
                self.assertEqual(result["variables"]["contentHub"]["currentArticle"], original["variables"]["contentHub"]["currentArticle"])

    def test_invalid_body_does_not_replace_fallback(self):
        for body in (None, 4, False):
            with self.subTest(body=body):
                published, _ = load_published(body)
                result = runtime._merge_content_hub_bundle_variables(payload(), published)
                self.assertEqual(result["variables"]["contentHub"]["currentArticle"]["articleContent"], ARTICLE["articleContent"])

    def test_unbound_package_does_not_replace_fallback(self):
        result = runtime._merge_content_hub_bundle_variables(payload(), {"variables": {"articleContent": {"html": "<p>Unbound body</p>"}}})
        self.assertEqual(result["variables"]["contentHub"]["currentArticle"]["articleContent"], ARTICLE["articleContent"])

    def test_current_article_identity_path_and_locale_must_match(self):
        published, _ = load_published({"html": "<p>Published body</p>"})
        for field, foreign in (("articleId", "art_other"), ("path", "/blog/web/other"), ("locale", "en")):
            with self.subTest(field=field):
                original = payload({**ARTICLE, field: foreign})
                result = runtime._merge_content_hub_bundle_variables(original, published)
                self.assertEqual(result["variables"]["contentHub"]["currentArticle"], original["variables"]["contentHub"]["currentArticle"])

    def test_bundle_identity_path_locale_and_publication_are_validated(self):
        for field, foreign in (("articleId", "art_other"), ("path", "/blog/web/other"), ("locale", "en"), ("status", "draft")):
            with self.subTest(field=field):
                published, _ = load_published({"html": "<p>Foreign body</p>"}, bundle_overrides={field: foreign})
                self.assertIsNone(published)

    def test_projection_copies_without_mutating_inputs_or_sharing_body(self):
        body = {"ops": [{"insert": "Exact body\n"}]}
        published, bundle = load_published(body)
        original = payload()
        before = copy.deepcopy((original, published, bundle))
        result = runtime._merge_content_hub_bundle_variables(original, published)
        self.assertEqual((original, published, bundle), before)
        self.assertEqual(result["variables"]["contentHub"]["currentArticle"]["articleContent"], body)
        result["variables"]["contentHub"]["currentArticle"]["articleContent"]["ops"][0]["insert"] = "Changed result only"
        self.assertEqual((original, published, bundle), before)

    def test_internal_binding_does_not_become_public_variables(self):
        published, _ = load_published({"html": "<p>Body</p>"})
        self.assertEqual(published.get("_articleBinding"), {"articleId": ARTICLE["articleId"], "path": PATH, "locale": "es"})
        result = runtime._merge_content_hub_bundle_variables(payload(), published)
        self.assertNotIn("_articleBinding", result)
        self.assertNotIn("_articleBinding", result["variables"])

    def test_legacy_package_without_locale_uses_its_validated_key(self):
        body = {"html": "<p>Legacy published body</p>"}
        published, _ = load_published(body, bundle_overrides={"locale": None})
        result = runtime._merge_content_hub_bundle_variables(payload(), published)
        self.assertEqual(result["variables"]["contentHub"]["currentArticle"]["articleContent"], body)

    def test_package_cannot_supply_its_own_binding(self):
        published, _ = load_published({"html": "<p>Published body</p>"}, bundle_overrides={
            "_articleBinding": {"articleId": "foreign", "path": "/foreign", "locale": "en"},
        })
        self.assertEqual(published["_articleBinding"], {"articleId": ARTICLE["articleId"], "path": PATH, "locale": "es"})

    def test_package_current_article_cannot_rebind_another_original_route(self):
        published, _ = load_published({"html": "<p>Published body</p>"})
        published["variables"]["contentHub"] = {"currentArticle": {
            key: ARTICLE[key] for key in ("articleId", "path", "locale")
        }}
        original = payload({**ARTICLE, "path": "/blog/web/foreign"})
        result = runtime._merge_content_hub_bundle_variables(original, published)
        self.assertEqual(result["variables"]["contentHub"]["currentArticle"]["articleContent"], ARTICLE["articleContent"])

    def test_package_current_article_is_not_mutated_when_original_payload_is_absent(self):
        published, _ = load_published({"ops": [{"insert": "Published Delta\n"}]})
        published["variables"]["contentHub"] = {"currentArticle": copy.deepcopy(ARTICLE)}
        before = copy.deepcopy(published)
        runtime._merge_content_hub_bundle_variables(None, published)
        self.assertEqual(published, before)

    def test_real_runtime_response_does_not_serialize_internal_binding(self):
        published, _ = load_published({"html": "<p>Published body</p>"})
        identity = {"version": 1, "domain": DOMAIN, "pageId": "blog-article"}
        result = runtime._published_bundle(
            request_id="synthetic", requested_domain=DOMAIN, domain=DOMAIN, resolved_alias=None,
            environment="production", version_id="synthetic", prefix="synthetic", path=PATH, lang="es",
            lifecycle={"status": "active"}, site_metadata={}, route={"path": PATH, "pageId": "blog-article"},
            page_id="blog-article", article_bundle=published,
            payloads={
                "siteConfig": {"domain": DOMAIN, "runtime": {"contentHubs": [copy.deepcopy(HUB)]}},
                "pageConfig": {**identity, "rootIds": []},
                "sharedComponents": None, "pageComponents": {**identity, "components": []},
                "sharedVariables": None, "pageVariables": payload(),
                "sharedAngoraCombos": None, "pageAngoraCombos": None,
                "sharedI18n": None, "pageI18n": None,
            },
        )
        self.assertNotIn("_articleBinding", str(result))
        self.assertEqual(result["variables"]["variables"]["contentHub"]["currentArticle"]["articleContent"], published["variables"]["articleContent"])
