import unittest
from unittest.mock import patch

import lambda_function as runtime


OWNER = "zoositioweb.com.mx"
READER = "zooberiahsystems.com"
HUB = {
    "hubId": "zoosite-main",
    "ownerDraftDomain": OWNER,
    "source": "authorized",
    "canonicalMode": "noindex-shared",
    "routeBasePath": "/blog",
    "listPath": "/blog",
    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
    "defaultLocale": "es",
    "locales": ["es"],
}
PATH = "/blog/web/guia"
ARTICLE = {
    "articleId": "art_public",
    "status": "published",
    "visibility": "public",
    "title": "Guía publicada",
    "path": PATH,
    "primaryLocale": "es",
    "publishedAt": "2026-11-13T00:00:00Z",
    "publishedBundleKey": f"content-hubs/prod/zoosite-main/published/{OWNER}/es/art_public/rev_1/bundle.json",
}


class SharedBlogTest(unittest.TestCase):
    def test_catalog_comes_from_same_environment_owner_and_filters_unpublished(self):
        static = {
            "articleId": "art_static",
            "status": "published",
            "locale": "es",
            "title": "Guía estática",
            "path": "/blog/web/estatica",
            "publishedAt": "2026-11-01T00:00:00Z",
            "articleContent": {"html": "<p>Artículo existente</p>"},
        }
        owner_config = {"domain": OWNER, "runtime": {"contentHubs": [
            {**HUB, "source": "primary", "publicArticles": [static]},
        ]}}
        cfg = {"domain": READER, "runtime": {"contentHubs": [HUB]}}
        with patch.object(runtime, "load_item", return_value={
            "publishedEnvironments": {"test": {"prefix": "test-source"}, "production": {"prefix": "prod-source"}}
        }), patch.object(runtime, "_load_payload", return_value=owner_config) as load, patch.object(
            runtime, "_content_hub_table_name", return_value="table"
        ), patch.object(runtime, "_query_content_hub_metadata", side_effect=lambda hub, kind, env: [
            ARTICLE, {**ARTICLE, "articleId": "art_draft", "status": "draft"},
            {**ARTICLE, "articleId": "art_private", "visibility": "private"},
        ] if kind == "ARTICLE#" else []) as query:
            result = runtime._merge_content_hub_runtime_indexes(cfg, "es", "test")
        articles = result["runtime"]["contentHubs"][0]["publicArticles"]
        self.assertEqual([item["articleId"] for item in articles], ["art_public", "art_static"])
        self.assertTrue(all(item["robots"] == "index,follow" for item in articles))
        self.assertTrue(all(item["primarySite"] == READER for item in articles))
        self.assertEqual(articles[1]["articleContent"], static["articleContent"])
        self.assertEqual(load.call_args.args[1:], ("test-source", f"{OWNER}/site-config.json"))
        self.assertTrue(all(call.args[-1] == "test" for call in query.call_args_list))

    def test_primary_site_applies_to_both_deliveries_and_preserves_noindex(self):
        for domain, hub in ((OWNER, {**HUB, "source": "primary"}), (READER, HUB)):
            for site in (None, OWNER, READER, "unrelated.example"):
                with self.subTest(domain=domain, primary_site=site):
                    cfg = {"domain": domain, "runtime": {"contentHubs": [hub]}}
                    with patch.object(runtime, "_shared_zoosite_owner_hub", return_value=hub), patch.object(
                        runtime, "_content_hub_table_name", return_value="table"
                    ), patch.object(runtime, "_query_content_hub_metadata", side_effect=lambda _hub, kind, _env: [
                        {**ARTICLE, "publishedPrimarySite": site}
                    ] if kind == "ARTICLE#" else []):
                        enriched = runtime._merge_content_hub_runtime_indexes(cfg, "es", "production")
                    article = enriched["runtime"]["contentHubs"][0]["publicArticles"][0]
                    primary = OWNER if site == OWNER else READER
                    robots = "index,follow" if primary == domain else "noindex,follow"
                    self.assertEqual(article["primarySite"], primary)
                    self.assertEqual(article["robots"], robots)
                    page = runtime._merge_content_hub_bundle_page_config_seo(
                        {"seo": {}}, enriched, {"seo": {"canonical": PATH, "robots": "index,follow"}}, article,
                    )
                    self.assertEqual(page["seo"]["canonical"], f"https://{primary}{PATH}")
                    self.assertEqual(page["seo"]["robots"], {"default": robots})

        restricted = runtime._zoosite_article_delivery({**ARTICLE, "robots": "noindex,nofollow"}, READER)
        self.assertEqual(restricted["robots"], "noindex,nofollow")

    def test_unauthorized_domain_cannot_subscribe(self):
        cfg = {"domain": "other.example", "runtime": {"contentHubs": [{**HUB, "publicArticles": [ARTICLE]}]}}
        with patch.object(runtime, "_content_hub_table_name", return_value="table"), patch.object(
            runtime, "_query_content_hub_metadata"
        ) as query:
            result = runtime._merge_content_hub_runtime_indexes(cfg, "es", "production")
        self.assertEqual(result["runtime"]["contentHubs"], [])
        query.assert_not_called()

    def test_published_only_reader_does_not_restore_unbound_owner_articles(self):
        cfg = {"domain": READER, "runtime": {"contentHubs": [{**HUB, "localePolicy": "published-only"}]}}
        with patch.object(runtime, "_shared_zoosite_owner_hub", return_value={"publicArticles": [{
            **ARTICLE, "locale": "es", "articleContent": {"html": "<p>Guía en español</p>"},
        }]}), patch.object(runtime, "_content_hub_table_name", return_value=""):
            result = runtime._merge_content_hub_runtime_indexes(cfg, "en", "test")
        self.assertEqual(result["runtime"]["contentHubs"][0]["publicArticles"], [])

    def test_shared_article_rebases_embed_sources_in_both_body_formats(self):
        html = "<p><img src='/media/guia.webp'><a href='/blog/web/otro'>Otro artículo</a></p>"
        self.assertEqual(runtime._shared_zoosite_content({"html": html}), {
            "html": html.replace("'/media/guia.webp'", f"'https://{OWNER}/media/guia.webp'"),
        })
        ops = [{"insert": {"image": "/blog/media/guia.webp"}}, {"insert": {"image": "//media.example/guia.webp"}}]
        self.assertEqual(runtime._shared_zoosite_content({"ops": ops}), {"ops": [
            {"insert": {"image": f"https://{OWNER}/blog/media/guia.webp"}}, ops[1],
        ]})

    def test_article_reads_original_public_bundle_before_projecting_reader_content(self):
        cfg = {"domain": READER, "runtime": {"contentHubs": [
            {**HUB, "publicArticles": [ARTICLE]},
        ]}}
        bundle = {
            "articleId": "art_public", "status": "published", "path": PATH,
            "variables": {"articleContent": {"ops": [
                {"insert": "Otro artículo", "attributes": {"link": "/blog/web/otro"}},
                {"insert": "Contacto", "attributes": {"link": "/contacto"}},
            ]}, "other": "ignored"},
            "components": [{"id": "foreign-component"}],
            "seo": {"title": "Guía", "canonical": PATH},
        }
        with patch.object(runtime, "_content_hub_table_name", return_value="table"), patch.object(
            runtime, "_content_hub_packages_bucket_name", return_value="bucket"
        ), patch.object(runtime, "_load_content_hub_article_metadata", return_value=ARTICLE), patch.object(
            runtime, "_load_content_hub_json_bundle", return_value=bundle
        ) as load, patch.object(runtime, "_load_content_hub_slug_pointer") as pointer:
            result = runtime._content_hub_bundle_for_path(cfg, PATH, "es", "production")
        self.assertEqual(load.call_args.args[3], OWNER)
        pointer.assert_not_called()
        self.assertNotIn("components", result)
        self.assertNotIn("other", result["variables"])
        ops = result["variables"]["articleContent"]["ops"]
        self.assertEqual(ops[0]["attributes"]["link"], "/blog/web/otro")
        self.assertEqual(ops[1]["attributes"]["link"], f"https://{OWNER}/contacto")
        article = {"primarySite": READER, "path": PATH, "robots": "index,follow"}
        page = runtime._merge_content_hub_bundle_page_config_seo({"seo": {}}, cfg, result, article)
        self.assertEqual(page["seo"]["canonical"], f"https://{READER}{PATH}")
        self.assertEqual(page["seo"]["robots"], {"default": "index,follow"})
