import importlib
import json
import unittest


class Context:
    aws_request_id = "runtime-request"


def parse(response):
    return json.loads(response["body"])


def event(host, path="/", lang="es", **query):
    query_params = {"path": path}
    if lang is not None:
        query_params["lang"] = lang
    query_params.update({key: value for key, value in query.items() if value is not None})
    return {
        "headers": {"host": host},
        "queryStringParameters": query_params,
        "requestContext": {"http": {"path": path}},
    }


class RuntimeHandlerTest(unittest.TestCase):
    def setUp(self):
        self.handler = importlib.reload(importlib.import_module("lambda_function"))
        self.metadata = {
            "pk": "SITE#pamelabetancourt.com",
            "sk": "METADATA",
            "domain": "pamelabetancourt.com",
            "aliases": ["pamelabetancourt.com"],
            "environmentAliases": {
                "test": ["test.pamelabetancourt.com", "test.pamelabetancourt.zoolandingpage.com.mx"]
            },
            "defaultPageId": "default",
            "routes": [{"path": "/", "pageId": "default"}],
            "contentHubs": [
                {
                    "hubId": "main",
                    "name": "Blog",
                    "defaultLanguage": "es",
                    "canonicalDraftDomain": "pamelabetancourt.com",
                    "allowedDraftDomains": ["pamelabetancourt.com", "sulandingpage.com.mx"],
                    "articleIds": ["primer-post"],
                    "serverOnly": {"token": "must-not-render"},
                }
            ],
            "lifecycle": {"status": "active"},
            "published": {"versionId": "prod-v1", "prefix": "prod-prefix"},
            "publishedEnvironments": {
                "production": {"versionId": "prod-v1", "prefix": "prod-prefix"},
                "test": {"versionId": "test-v1", "prefix": "test-prefix"},
                "dev": {"versionId": "dev-v1", "prefix": "dev-prefix"},
            },
        }
        self.canonical_metadata = {
            "pk": "SITE#zoolandingpage.com.mx",
            "sk": "METADATA",
            "domain": "zoolandingpage.com.mx",
            "aliases": ["zoolandingpage.com.mx"],
            "environmentAliases": {
                "test": ["test.zoolandingpage.com.mx"]
            },
            "defaultPageId": "default",
            "notFoundPageId": "not-found",
            "routes": [
                {"path": "/", "pageId": "default"},
                {"path": "/404", "pageId": "not-found", "label": "Not found"},
            ],
            "lifecycle": {"status": "active"},
            "published": {"versionId": "canonical-prod-v1", "prefix": "canonical-prod-prefix"},
            "publishedEnvironments": {
                "production": {"versionId": "canonical-prod-v1", "prefix": "canonical-prod-prefix"},
                "test": {"versionId": "canonical-test-v1", "prefix": "canonical-test-prefix"},
            },
        }
        self.items = {
            ("SITE#pamelabetancourt.com", "METADATA"): self.metadata,
            ("SITE#zoolandingpage.com.mx", "METADATA"): self.canonical_metadata,
            ("ALIAS#test.pamelabetancourt.com", "SITE"): {
                "domain": "pamelabetancourt.com",
                "alias": "test.pamelabetancourt.com",
                "environment": "test",
            },
            ("ALIAS#pamelabetancourt.com", "SITE"): {
                "domain": "pamelabetancourt.com",
                "alias": "pamelabetancourt.com",
                "environment": "production",
            },
        }
        self.payloads = {}
        self.package_payloads = {}
        self.loaded_keys = []
        self.content_hub_items = []

        for prefix in ("prod-prefix", "test-prefix", "dev-prefix"):
            self.put_site(prefix, "pamelabetancourt.com", include_not_found=True)
            self.put_page(prefix, "pamelabetancourt.com", "default", "Hero")
            self.put_page(prefix, "pamelabetancourt.com", "not-found", "Page not found")

        for prefix in ("canonical-prod-prefix", "canonical-test-prefix"):
            self.put_site(prefix, "zoolandingpage.com.mx", include_not_found=True)
            self.put_page(prefix, "zoolandingpage.com.mx", "default", "Canonical hero")
            self.put_page(prefix, "zoolandingpage.com.mx", "not-found", "Canonical 404")

        def load_item(_table, pk, sk="METADATA"):
            return self.items.get((pk, sk))

        def load_json(bucket, key):
            self.loaded_keys.append(key)
            if bucket == "content-hub-packages-test":
                return self.package_payloads.get(key)
            return self.payloads.get(key)

        class FakeContentHubTable:
            def __init__(self, owner, table_name):
                self.owner = owner
                self.table_name = table_name

            def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, Limit=None, ExclusiveStartKey=None):
                del KeyConditionExpression
                expression_values = ExpressionAttributeValues or {}
                pk = expression_values.get(":pk")
                sk_prefix = expression_values.get(":sk")
                matches = [
                    dict(item)
                    for item in self.owner.content_hub_items
                    if item.get("pk") == pk and str(item.get("sk") or "").startswith(str(sk_prefix or ""))
                    and str(item.get("tableName") or self.table_name) == self.table_name
                ]
                start = int((ExclusiveStartKey or {}).get("index", 0))
                page_size = int(Limit or len(matches) or 1)
                page = matches[start:start + page_size]
                response = {"Items": page}
                if start + page_size < len(matches):
                    response["LastEvaluatedKey"] = {"index": start + page_size}
                return response

        def get_table(table_name):
            if table_name in {"content-hub-metadata", "content-hub-metadata-dev", "content-hub-metadata-test", "content-hub-metadata-prod"}:
                return FakeContentHubTable(self, table_name)
            raise AssertionError(f"Unexpected table requested: {table_name}")

        self.handler.load_item = load_item
        self.handler.load_json_from_s3 = load_json
        self.handler.get_table = get_table

    def put_payload(self, prefix, domain, relative_path, payload):
        self.payloads[f"{prefix}/{domain}/{relative_path}"] = payload

    def put_site(self, prefix, domain, include_not_found):
        routes = [{"path": "/", "pageId": "default"}]
        payload = {
            "domain": domain,
            "defaultPageId": "default",
            "routes": routes,
            "contentHubs": [
                {
                    "hubId": "main",
                    "name": "Blog",
                    "defaultLanguage": "es",
                    "canonicalDraftDomain": domain,
                    "allowedDraftDomains": [domain, "sulandingpage.com.mx"],
                    "serverOnly": {"token": "must-not-render"},
                    "articleIds": ["primer-post"],
                }
            ],
        }
        if include_not_found:
            payload["notFoundPageId"] = "not-found"
            routes.append({"path": "/404", "pageId": "not-found", "label": "Not found"})
        self.put_payload(prefix, domain, "site-config.json", payload)
        self.put_payload(prefix, domain, "components.json", {"components": []})
        self.put_payload(prefix, domain, "variables.json", {"variables": {}})
        self.put_payload(prefix, domain, "angora-combos.json", {"combos": {}})
        self.put_payload(prefix, domain, "i18n/es.json", {"lang": "es", "dictionary": {"shared": "Compartido"}})
        self.put_payload(prefix, domain, "i18n/en.json", {"lang": "en", "dictionary": {"shared": "Shared"}})

    def put_page(self, prefix, domain, page_id, text):
        self.put_payload(prefix, domain, f"{page_id}/page-config.json", {"pageId": page_id, "rootIds": ["hero"]})
        self.put_payload(
            prefix,
            domain,
            f"{page_id}/components.json",
            {"pageId": page_id, "components": [{"id": "hero", "type": "text", "config": {"text": text}}]},
        )
        self.put_payload(prefix, domain, f"{page_id}/variables.json", {"pageId": page_id, "variables": {}})
        self.put_payload(prefix, domain, f"{page_id}/angora-combos.json", {"pageId": page_id, "combos": {}})
        self.put_payload(prefix, domain, f"{page_id}/i18n/es.json", {"pageId": page_id, "lang": "es", "dictionary": {"title": f"{text} ES"}})
        self.put_payload(prefix, domain, f"{page_id}/i18n/en.json", {"pageId": page_id, "lang": "en", "dictionary": {"title": f"{text} EN"}})

    def test_test_alias_uses_test_published_pointer(self):
        response = self.handler.lambda_handler(event("test.pamelabetancourt.com"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["environment"], "test")
        self.assertEqual(body["versionId"], "test-v1")
        self.assertEqual(body["pageId"], "default")
        self.assertEqual(body["metadata"]["statusCode"], 200)
        self.assertFalse(body["metadata"]["notFound"])
        self.assertTrue(any(key.startswith("test-prefix/") for key in self.loaded_keys))

    def test_production_alias_uses_production_pointer(self):
        response = self.handler.lambda_handler(event("pamelabetancourt.com"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["environment"], "production")
        self.assertEqual(body["versionId"], "prod-v1")
        self.assertEqual(body["pageId"], "default")
        self.assertTrue(any(key.startswith("prod-prefix/") for key in self.loaded_keys))

    def test_canonical_domain_environment_query_uses_test_pointer(self):
        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["domain"], "pamelabetancourt.com")
        self.assertEqual(body["environment"], "test")
        self.assertEqual(body["versionId"], "test-v1")
        self.assertEqual(body["metadata"]["requestedDomain"], "pamelabetancourt.com")
        self.assertIsNone(body["metadata"]["resolvedAlias"])
        self.assertTrue(any(key.startswith("test-prefix/") for key in self.loaded_keys))

    def test_canonical_domain_environment_query_uses_dev_pointer(self):
        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", domain="pamelabetancourt.com", environment="dev"),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["environment"], "dev")
        self.assertEqual(body["versionId"], "dev-v1")
        self.assertTrue(any(key.startswith("dev-prefix/") for key in self.loaded_keys))

    def test_parameterized_category_route_resolves_page_payload(self):
        self.metadata["routes"].append({"path": "/blog/:categorySlug", "pageId": "blog-category"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-category", "Category page")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].append({"path": "/blog/:categorySlug", "pageId": "blog-category"})

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["environment"], "test")
        self.assertEqual(body["pageId"], "blog-category")
        self.assertEqual(body["route"]["path"], "/blog/:categorySlug")
        self.assertFalse(body["metadata"]["notFound"])

    def test_runtime_bundle_exposes_public_content_hub_metadata(self):
        response = self.handler.lambda_handler(event("pamelabetancourt.com"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertNotIn("bucket", body["metadata"])
        self.assertNotIn("prefix", body["metadata"])
        self.assertEqual(body["metadata"]["contentHubs"][0]["hubId"], "main")
        self.assertNotIn("articleIds", body["metadata"]["contentHubs"][0])
        self.assertNotIn("allowedDraftDomains", body["metadata"]["contentHubs"][0])
        self.assertNotIn("serverOnly", body["metadata"]["contentHubs"][0])

    def test_runtime_bundle_hydrates_public_content_hub_indexes_from_metadata_table(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME = "content-hub-metadata"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article page")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "empty",
                    "routeBasePath": "/news",
                    "articlePathPattern": "/news/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [],
                },
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "defaultLocale": "es",
                    "locales": ["es", "en"],
                    "publicArticles": [
                        {
                            "articleId": "seed",
                            "locale": "es",
                            "status": "published",
                            "title": "Seed",
                            "summary": "Seed summary",
                            "path": "/blog/web/seed",
                            "categorySlug": "web",
                            "tags": ["seed"],
                            "publishedAt": "2026-06-20T01:00:00Z",
                            "robots": "index,follow",
                        }
                    ],
                }
            ]
        }
        self.content_hub_items = [
            {
                "pk": "HUB#main",
                "sk": "ARTICLE#art_public",
                "articleId": "art_public",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "QA E2E",
                "summary": "Resumen publico",
                "path": "/blog/web/qa-e2e",
                "category": {"taxonomyId": "web"},
                "tags": [{"taxonomyId": "qa"}, {"slug": "content-hub"}],
                "imageSrc": "https://images.example.test/blog/qa-e2e.jpg?fit=cover",
                "imageAlt": "Equipo editando un articulo visual",
                "coverImage": "https://images.example.test/blog/old-cover.jpg",
                "privateImageUrl": "https://example.test/private.jpg?X-Amz-Signature=must-not-render",
                "publishedAt": "2026-06-27T22:48:09Z",
                "updatedAt": "2026-06-27T22:48:10Z",
                "authorLabel": "Equipo editorial",
                "commentPolicy": "authenticated",
                "contentSafety": {"rating": "sensitive", "warnings": ["sanitizado"]},
                "interactions": {
                    "reactions": {"enabled": True, "moderation": "spam-check"},
                    "ctas": {"enabled": True, "moderation": "spam-check"},
                    "forms": {"enabled": False, "moderation": "queue"},
                },
                "articleContent": {"html": "<h2>Contenido publico</h2>"},
                "publishedBundleKey": "must-not-render",
                "updatedBy": "must-not-render",
            },
            {
                "pk": "HUB#main",
                "sk": "ARTICLE#art_private",
                "articleId": "art_private",
                "status": "published",
                "visibility": "private",
                "primaryLocale": "es",
                "title": "Private",
                "path": "/blog/web/private",
                "publishedAt": "2026-06-27T22:48:09Z",
            },
            {
                "pk": "HUB#main",
                "sk": "ARTICLE#art_draft",
                "articleId": "art_draft",
                "status": "draft",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "Draft",
                "path": "/blog/web/draft",
                "publishedAt": "2026-06-27T22:48:09Z",
            },
        ]

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/qa-e2e", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)
        serialized = response["body"]

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["pageId"], "blog-article")
        main_hub = next(hub for hub in body["siteConfig"]["runtime"]["contentHubs"] if hub["hubId"] == "main")
        articles = main_hub["publicArticles"]
        self.assertEqual(articles[0]["articleId"], "art_public")
        self.assertEqual(articles[0]["path"], "/blog/web/qa-e2e")
        self.assertEqual(articles[0]["imageSrc"], "https://images.example.test/blog/qa-e2e.jpg?fit=cover")
        self.assertEqual(articles[0]["imageAlt"], "Equipo editando un articulo visual")
        self.assertNotIn("publishedBundleKey", articles[0])
        self.assertNotIn("updatedBy", articles[0])
        self.assertNotIn("coverImage", articles[0])
        self.assertNotIn("privateImageUrl", serialized)
        self.assertNotIn("art_private", serialized)
        self.assertNotIn("art_draft", serialized)
        self.assertNotIn("must-not-render", serialized)
        current_article = body["variables"]["variables"]["contentHub"]["currentArticle"]
        self.assertEqual(body["variables"]["variables"]["contentHub"]["hubId"], "main")
        self.assertEqual(current_article["articleId"], "art_public")
        self.assertEqual(current_article["summary"], "Resumen publico")
        self.assertEqual(current_article["articleContent"], {"html": "<h2>Contenido publico</h2>"})
        self.assertEqual(current_article["imageSrc"], "https://images.example.test/blog/qa-e2e.jpg?fit=cover")
        self.assertEqual(current_article["imageAlt"], "Equipo editando un articulo visual")
        self.assertEqual(current_article["commentPolicy"], "authenticated")
        self.assertEqual(current_article["contentSafety"], {"rating": "sensitive", "warnings": ["sanitizado"]})
        self.assertEqual(current_article["interactions"]["forms"], {"enabled": False, "moderation": "queue"})
        self.assertNotIn("bodyHash", serialized)
        seo = body["pageConfig"]["seo"]
        self.assertEqual(seo["title"], "QA E2E | pamelabetancourt.com")
        self.assertEqual(seo["description"], "Resumen publico")
        self.assertEqual(seo["canonical"], "https://pamelabetancourt.com/blog/web/qa-e2e")
        self.assertEqual(seo["robots"], {"default": "index,follow"})
        categories = body["variables"]["variables"]["contentHub"]["categories"]["items"]
        tags = body["variables"]["variables"]["contentHub"]["tags"]["items"]
        self.assertTrue(any(item["slug"] == "web" for item in categories))
        self.assertTrue(any(item["slug"] == "qa" for item in tags))

    def test_dynamic_content_hub_article_uses_safe_static_cover_fallback(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME = "content-hub-metadata"
        self.metadata["routes"].append({"path": "/blog", "pageId": "blog"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog", "Blog")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [
                        {
                            "articleId": "art_without_dynamic_image",
                            "status": "published",
                            "title": "Static title must not win",
                            "summary": "Static summary must not win",
                            "path": "/blog/web/static-path-must-not-win",
                            "publishedAt": "2026-06-20T01:00:00Z",
                            "imageSrc": "https://images.example.test/blog/static-cover.jpg",
                            "imageAlt": "Static cover fallback",
                            "heroImageUrl": "https://example.test/private.jpg?X-Amz-Signature=must-not-render",
                        }
                    ],
                }
            ]
        }
        self.content_hub_items = [
            {
                "pk": "HUB#main",
                "sk": "ARTICLE#art_without_dynamic_image",
                "articleId": "art_without_dynamic_image",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "Dynamic title wins",
                "summary": "Dynamic summary wins",
                "path": "/blog/web/dynamic-path-wins",
                "category": {"taxonomyId": "web"},
                "tags": [{"taxonomyId": "qa"}],
                "publishedAt": "2026-06-27T22:48:09Z",
            },
        ]

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)
        serialized = response["body"]

        self.assertEqual(response["statusCode"], 200)
        article = body["siteConfig"]["runtime"]["contentHubs"][0]["publicArticles"][0]
        self.assertEqual(article["articleId"], "art_without_dynamic_image")
        self.assertEqual(article["title"], "Dynamic title wins")
        self.assertEqual(article["summary"], "Dynamic summary wins")
        self.assertEqual(article["path"], "/blog/web/dynamic-path-wins")
        self.assertEqual(article["imageSrc"], "https://images.example.test/blog/static-cover.jpg")
        self.assertEqual(article["imageAlt"], "Static cover fallback")
        self.assertNotIn("static-path-must-not-win", serialized)
        self.assertNotIn("must-not-render", serialized)

    def test_runtime_bundle_hydrates_localized_public_content_hub_article(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME = "content-hub-metadata"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article page")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es", "en"],
                    "publicArticles": [],
                }
            ]
        }
        self.content_hub_items = [
            {
                "pk": "HUB#main",
                "sk": "ARTICLE#art_public",
                "articleId": "art_public",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "Artículo ES",
                "summary": "Resumen ES",
                "path": "/blog/web/articulo-es",
                "category": {"taxonomyId": "web"},
                "tags": [{"taxonomyId": "seo"}],
                "publishedAt": "2026-06-27T22:48:09Z",
                "imageSrc": "https://images.example.test/blog/articulo-es.jpg",
                "imageAlt": "Imagen de portada en espanol",
                "articleContent": {"html": "<h2>Contenido ES</h2>"},
                "localizations": {
                    "en": {
                        "title": "English article",
                        "summary": "English summary",
                        "path": "/blog/web/english-article",
                        "canonicalPath": "/blog/web/english-article",
                        "categorySlug": "web",
                        "tags": ["seo", "guides"],
                        "imageSrc": "https://images.example.test/blog/english-article.jpg",
                        "imageAlt": "English cover image",
                        "articleContent": {"html": "<h2>English content</h2>"},
                    }
                },
                "publishedBundleKey": "must-not-render",
            }
        ]

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/english-article", lang="en", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)
        serialized = response["body"]

        self.assertEqual(response["statusCode"], 200)
        main_hub = next(hub for hub in body["siteConfig"]["runtime"]["contentHubs"] if hub["hubId"] == "main")
        self.assertEqual(main_hub["publicArticles"][0]["locale"], "en")
        self.assertEqual(main_hub["publicArticles"][0]["title"], "English article")
        self.assertEqual(main_hub["publicArticles"][0]["path"], "/blog/web/english-article")
        self.assertEqual(main_hub["publicArticles"][0]["imageSrc"], "https://images.example.test/blog/english-article.jpg")
        self.assertEqual(main_hub["publicArticles"][0]["imageAlt"], "English cover image")
        current_article = body["variables"]["variables"]["contentHub"]["currentArticle"]
        self.assertEqual(current_article["articleId"], "art_public")
        self.assertEqual(current_article["locale"], "en")
        self.assertEqual(current_article["summary"], "English summary")
        self.assertEqual(current_article["articleContent"], {"html": "<h2>English content</h2>"})
        self.assertEqual(current_article["imageSrc"], "https://images.example.test/blog/english-article.jpg")
        self.assertEqual(current_article["imageAlt"], "English cover image")
        self.assertNotIn("publishedBundleKey", serialized)

    def test_runtime_bundle_repairs_mojibake_from_published_site_config_articles(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME = "content-hub-metadata"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article page")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [
                        {
                            "articleId": "art_mojibake",
                            "locale": "es",
                            "status": "published",
                            "title": "CÃ³mo crear artÃ­culos visuales",
                            "summary": "GuÃ­a prÃ¡ctica para publicar con mediciÃ³n.",
                            "path": "/blog/web/mojibake",
                            "categorySlug": "web",
                            "publishedAt": "2026-06-27T22:48:09Z",
                        }
                    ],
                }
            ]
        }

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/mojibake", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)
        article = body["variables"]["variables"]["contentHub"]["currentArticle"]

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(article["title"], "Cómo crear artículos visuales")
        self.assertEqual(article["summary"], "Guía práctica para publicar con medición.")
        self.assertNotIn("CÃ³mo", response["body"])

    def test_runtime_bundle_treats_missing_article_visibility_as_public(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article page")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [],
                }
            ]
        }
        self.content_hub_items = [
            {
                "tableName": "content-hub-metadata-test",
                "pk": "HUB#main",
                "sk": "ARTICLE#art_public",
                "articleId": "art_public",
                "status": "published",
                "primaryLocale": "es",
                "title": "QA Sin visibility",
                "summary": "Resumen publico sin campo visibility",
                "path": "/blog/web/sin-visibility",
                "category": {"taxonomyId": "web"},
                "tags": [{"taxonomyId": "qa"}],
                "publishedAt": "2026-06-27T22:48:09Z",
            },
        ]

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/sin-visibility", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["pageId"], "blog-article")
        self.assertEqual(body["metadata"]["statusCode"], 200)
        self.assertFalse(body["metadata"]["notFound"])
        self.assertEqual(body["variables"]["variables"]["contentHub"]["currentArticle"]["articleId"], "art_public")

    def test_runtime_bundle_merges_published_content_hub_article_bundle(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.handler.CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST = "content-hub-packages-test"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article shell")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [],
                }
            ]
        }
        bundle_key = "content-hubs/test/main/published/pamelabetancourt.com/es/art_public/rev_1/bundle.json"
        self.content_hub_items = [
            {
                "tableName": "content-hub-metadata-test",
                "pk": "HUB#main",
                "sk": "ARTICLE#art_public",
                "articleId": "art_public",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "QA E2E",
                "summary": "Resumen publico",
                "path": "/blog/web/qa-e2e",
                "category": {"taxonomyId": "web"},
                "tags": [{"taxonomyId": "qa"}],
                "publishedAt": "2026-06-27T22:48:09Z",
                "publishedBundleKey": bundle_key,
            }
        ]
        self.package_payloads[bundle_key] = {
            "version": 1,
            "kind": "content-hub-published-bundle",
            "articleId": "art_public",
            "path": "/blog/web/qa-e2e",
            "status": "published",
            "seo": {
                "title": "SEO desde bundle",
                "description": "Descripcion desde bundle",
                "canonical": "/blog/web/qa-e2e",
                "robots": "index,follow,max-image-preview:large",
            },
            "components": [
                {"id": "articleBody", "type": "text", "config": {"text": "Cuerpo real publicado"}}
            ],
            "variables": {"articleBody": {"html": "<p>Cuerpo real publicado</p>"}},
            "i18n": {"dictionary": {"article.body": "Cuerpo real publicado"}},
        }

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/qa-e2e", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)
        serialized = response["body"]

        self.assertEqual(response["statusCode"], 200)
        self.assertIn(bundle_key, self.loaded_keys)
        self.assertIn("Cuerpo real publicado", serialized)
        self.assertEqual(body["components"]["components"][-1]["id"], "articleBody")
        self.assertEqual(body["variables"]["variables"]["contentHub"]["currentArticle"]["articleId"], "art_public")
        self.assertEqual(body["variables"]["variables"]["articleBody"]["html"], "<p>Cuerpo real publicado</p>")
        self.assertEqual(body["i18n"]["dictionary"]["article.body"], "Cuerpo real publicado")
        self.assertEqual(body["pageConfig"]["seo"]["title"], "SEO desde bundle | pamelabetancourt.com")
        self.assertEqual(body["pageConfig"]["seo"]["description"], "Descripcion desde bundle")
        self.assertEqual(body["pageConfig"]["seo"]["canonical"], "https://pamelabetancourt.com/blog/web/qa-e2e")
        self.assertNotIn("publishedBundleKey", serialized)

    def test_missing_lang_uses_site_default_language_for_content_hub_article_bundle(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.handler.CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST = "content-hub-packages-test"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article shell")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["site"] = {"i18n": {"defaultLanguage": "es"}}
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es", "en"],
                    "publicArticles": [],
                }
            ]
        }
        bundle_key = "content-hubs/test/main/published/pamelabetancourt.com/es/art_public/rev_1/bundle.json"
        self.content_hub_items = [
            {
                "tableName": "content-hub-metadata-test",
                "pk": "HUB#main",
                "sk": "ARTICLE#art_public",
                "articleId": "art_public",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "QA E2E",
                "summary": "Resumen publico",
                "path": "/blog/web/qa-e2e",
                "category": {"taxonomyId": "web"},
                "tags": [{"taxonomyId": "qa"}],
                "publishedAt": "2026-06-27T22:48:09Z",
                "publishedBundleKey": bundle_key,
            }
        ]
        self.package_payloads[bundle_key] = {
            "version": 1,
            "kind": "content-hub-published-bundle",
            "articleId": "art_public",
            "path": "/blog/web/qa-e2e",
            "status": "published",
            "components": [{"id": "articleBody", "type": "text", "config": {"text": "Cuerpo real publicado"}}],
            "variables": {"articleBody": {"html": "<p>Cuerpo real publicado</p>"}},
        }

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/qa-e2e", lang=None, domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["lang"], "es")
        self.assertIn(bundle_key, self.loaded_keys)
        self.assertEqual(body["pageId"], "blog-article")
        self.assertEqual(body["variables"]["variables"]["contentHub"]["currentArticle"]["articleId"], "art_public")
        self.assertEqual(body["components"]["components"][-1]["id"], "articleBody")

    def test_explicit_lang_does_not_fall_back_to_site_default_for_content_hub_article_bundle(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.handler.CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST = "content-hub-packages-test"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article shell")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["site"] = {"i18n": {"defaultLanguage": "es"}}
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es", "en"],
                    "publicArticles": [],
                }
            ]
        }
        bundle_key = "content-hubs/test/main/published/pamelabetancourt.com/es/art_public/rev_1/bundle.json"
        self.content_hub_items = [
            {
                "tableName": "content-hub-metadata-test",
                "pk": "HUB#main",
                "sk": "ARTICLE#art_public",
                "articleId": "art_public",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "QA E2E",
                "path": "/blog/web/qa-e2e",
                "publishedAt": "2026-06-27T22:48:09Z",
                "publishedBundleKey": bundle_key,
            }
        ]
        self.package_payloads[bundle_key] = {
            "articleId": "art_public",
            "path": "/blog/web/qa-e2e",
            "status": "published",
            "components": [{"id": "articleBody", "type": "text"}],
        }

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/qa-e2e", lang="en", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["lang"], "en")
        self.assertEqual(body["pageId"], "not-found")
        self.assertEqual(body["metadata"]["statusCode"], 404)
        self.assertNotIn(bundle_key, self.loaded_keys)

    def test_runtime_bundle_uses_slug_pointer_bundle_key_for_legacy_published_articles(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.handler.CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST = "content-hub-packages-test"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article shell")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [],
                }
            ]
        }
        bundle_key = "content-hubs/test/main/published/pamelabetancourt.com/es/art_public/rev_1/bundle.json"
        self.items[("SLUG#test#pamelabetancourt.com#es", "PATH#/blog/web/qa-e2e")] = {
            "pk": "SLUG#test#pamelabetancourt.com#es",
            "sk": "PATH#/blog/web/qa-e2e",
            "articleId": "art_public",
            "revisionId": "rev_1",
            "path": "/blog/web/qa-e2e",
            "publishedBundleKey": bundle_key,
        }
        self.content_hub_items = [
            {
                "tableName": "content-hub-metadata-test",
                "pk": "HUB#main",
                "sk": "ARTICLE#art_public",
                "articleId": "art_public",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "QA E2E",
                "summary": "Resumen publico",
                "path": "/blog/web/qa-e2e",
                "category": {"taxonomyId": "web"},
                "tags": [{"taxonomyId": "qa"}],
                "publishedAt": "2026-06-27T22:48:09Z",
            }
        ]
        self.package_payloads[bundle_key] = {
            "version": 1,
            "kind": "content-hub-published-bundle",
            "articleId": "art_public",
            "path": "/blog/web/qa-e2e",
            "status": "published",
            "components": [{"id": "legacyArticleBody", "type": "text", "config": {"text": "Legacy bundle body"}}],
            "variables": {"legacyArticleBody": {"html": "<p>Legacy bundle body</p>"}},
        }

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/qa-e2e", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)
        serialized = response["body"]

        self.assertEqual(response["statusCode"], 200)
        self.assertIn(bundle_key, self.loaded_keys)
        self.assertEqual(body["pageId"], "blog-article")
        self.assertEqual(body["components"]["components"][-1]["id"], "legacyArticleBody")
        self.assertEqual(body["variables"]["variables"]["legacyArticleBody"]["html"], "<p>Legacy bundle body</p>")
        self.assertNotIn("publishedBundleKey", serialized)

    def test_runtime_bundle_ignores_slug_pointer_for_different_article(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.handler.CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST = "content-hub-packages-test"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article shell")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [],
                }
            ]
        }
        bundle_key = "content-hubs/test/main/published/pamelabetancourt.com/es/other_article/rev_1/bundle.json"
        self.items[("SLUG#test#pamelabetancourt.com#es", "PATH#/blog/web/qa-e2e")] = {
            "pk": "SLUG#test#pamelabetancourt.com#es",
            "sk": "PATH#/blog/web/qa-e2e",
            "articleId": "other_article",
            "revisionId": "rev_1",
            "path": "/blog/web/qa-e2e",
            "publishedBundleKey": bundle_key,
        }
        self.content_hub_items = [
            {
                "tableName": "content-hub-metadata-test",
                "pk": "HUB#main",
                "sk": "ARTICLE#art_public",
                "articleId": "art_public",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "QA E2E",
                "path": "/blog/web/qa-e2e",
                "publishedAt": "2026-06-27T22:48:09Z",
            }
        ]
        self.package_payloads[bundle_key] = {
            "articleId": "other_article",
            "path": "/blog/web/qa-e2e",
            "status": "published",
            "components": [{"id": "evilBody", "type": "text"}],
        }

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/qa-e2e", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)

        self.assertEqual(body["pageId"], "blog-article")
        self.assertEqual(body["metadata"]["statusCode"], 200)
        self.assertEqual(body["variables"]["variables"]["contentHub"]["currentArticle"]["articleId"], "art_public")
        self.assertNotIn(bundle_key, self.loaded_keys)

    def test_missing_content_hub_article_path_renders_configured_404(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article shell")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [],
                }
            ]
        }

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/no-existe", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["pageId"], "not-found")
        self.assertEqual(body["metadata"]["statusCode"], 404)
        self.assertTrue(body["metadata"]["notFound"])
        self.assertNotIn("Article shell", response["body"])

    def test_missing_content_hub_taxonomy_paths_render_configured_404(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.metadata["routes"].extend([
            {"path": "/blog/:categorySlug", "pageId": "blog-category"},
            {"path": "/blog/tag/:tagSlug", "pageId": "blog-tag"},
        ])
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-category", "Category shell")
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-tag", "Tag shell")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].extend([
            {"path": "/blog/:categorySlug", "pageId": "blog-category"},
            {"path": "/blog/tag/:tagSlug", "pageId": "blog-tag"},
        ])
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [],
                    "publicTaxonomy": [],
                }
            ]
        }

        category_response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/bienvenido-al-blog-de-zoosite", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        tag_response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/tag/no-existe", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        category_body = parse(category_response)
        tag_body = parse(tag_response)

        self.assertEqual(category_response["statusCode"], 200)
        self.assertEqual(category_body["pageId"], "not-found")
        self.assertEqual(category_body["metadata"]["statusCode"], 404)
        self.assertTrue(category_body["metadata"]["notFound"])
        self.assertNotIn("Category shell", category_response["body"])
        self.assertEqual(tag_response["statusCode"], 200)
        self.assertEqual(tag_body["pageId"], "not-found")
        self.assertEqual(tag_body["metadata"]["statusCode"], 404)
        self.assertTrue(tag_body["metadata"]["notFound"])
        self.assertNotIn("Tag shell", tag_response["body"])

    def test_content_hub_article_with_missing_bundle_uses_article_shell(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.handler.CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST = "content-hub-packages-test"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article shell")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [],
                }
            ]
        }
        self.content_hub_items = [
            {
                "tableName": "content-hub-metadata-test",
                "pk": "HUB#main",
                "sk": "ARTICLE#art_public",
                "articleId": "art_public",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "QA E2E",
                "path": "/blog/web/qa-e2e",
                "publishedAt": "2026-06-27T22:48:09Z",
                "publishedBundleKey": "content-hubs/test/main/published/pamelabetancourt.com/es/art_public/rev_1/bundle.json",
            }
        ]

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/qa-e2e", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)

        self.assertEqual(body["pageId"], "blog-article")
        self.assertEqual(body["metadata"]["statusCode"], 200)
        self.assertFalse(body["metadata"]["notFound"])
        self.assertIn("Article shell", response["body"])
        self.assertEqual(body["variables"]["variables"]["contentHub"]["currentArticle"]["articleId"], "art_public")

    def test_content_hub_bundle_key_must_match_article_context_before_merging(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.handler.CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST = "content-hub-packages-test"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article shell")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [],
                }
            ]
        }
        foreign_key = "content-hubs/test/other/published/evil.example/es/art_public/rev_1/bundle.json"
        self.content_hub_items = [
            {
                "tableName": "content-hub-metadata-test",
                "pk": "HUB#main",
                "sk": "ARTICLE#art_public",
                "articleId": "art_public",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "QA E2E",
                "path": "/blog/web/qa-e2e",
                "publishedAt": "2026-06-27T22:48:09Z",
                "publishedBundleKey": foreign_key,
            }
        ]
        self.package_payloads[foreign_key] = {
            "articleId": "art_public",
            "path": "/blog/web/qa-e2e",
            "status": "published",
            "components": [{"id": "evilBody", "type": "text", "config": {"text": "No debe renderizar"}}],
        }

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/qa-e2e", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)

        self.assertEqual(body["pageId"], "blog-article")
        self.assertEqual(body["metadata"]["statusCode"], 200)
        self.assertEqual(body["variables"]["variables"]["contentHub"]["currentArticle"]["articleId"], "art_public")
        self.assertNotIn(foreign_key, self.loaded_keys)
        self.assertNotIn("No debe renderizar", response["body"])

    def test_runtime_bundle_uses_environment_specific_content_hub_table(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME = "content-hub-metadata-prod"
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [],
                }
            ]
        }
        self.content_hub_items = [
            {
                "tableName": "content-hub-metadata-prod",
                "pk": "HUB#main",
                "sk": "ARTICLE#art_prod",
                "articleId": "art_prod",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "Prod Article",
                "path": "/blog/web/prod",
                "publishedAt": "2026-06-27T22:48:09Z",
            },
            {
                "tableName": "content-hub-metadata-test",
                "pk": "HUB#main",
                "sk": "ARTICLE#art_test",
                "articleId": "art_test",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": "Test Article",
                "path": "/blog/web/test",
                "publishedAt": "2026-06-27T22:48:10Z",
            },
        ]

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)
        serialized = response["body"]
        articles = body["siteConfig"]["runtime"]["contentHubs"][0]["publicArticles"]

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["environment"], "test")
        self.assertEqual(articles[0]["articleId"], "art_test")
        self.assertIn("Test Article", serialized)
        self.assertNotIn("Prod Article", serialized)

    def test_runtime_bundle_reads_all_paginated_content_hub_metadata(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME = "content-hub-metadata-test"
        self.metadata["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article page")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].append({"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"})
        site_config["runtime"] = {
            "contentHubs": [
                {
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [],
                }
            ]
        }
        self.content_hub_items = [
            {
                "tableName": "content-hub-metadata-test",
                "pk": "HUB#main",
                "sk": f"ARTICLE#art_{index:03d}",
                "articleId": f"art_{index:03d}",
                "status": "published",
                "visibility": "public",
                "primaryLocale": "es",
                "title": f"Article {index}",
                "path": f"/blog/web/article-{index}",
                "publishedAt": "2026-06-27T22:48:10Z",
            }
            for index in range(201)
        ]

        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", path="/blog/web/article-200", domain="pamelabetancourt.com", environment="test"),
            Context(),
        )
        body = parse(response)
        articles = body["siteConfig"]["runtime"]["contentHubs"][0]["publicArticles"]

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["pageId"], "blog-article")
        self.assertEqual(body["variables"]["variables"]["contentHub"]["currentArticle"]["articleId"], "art_200")
        self.assertEqual(len(articles), 201)

    def test_unknown_route_uses_configured_not_found_page_id(self):
        response = self.handler.lambda_handler(event("test.pamelabetancourt.com", "/missing", "en"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["domain"], "pamelabetancourt.com")
        self.assertEqual(body["pageId"], "not-found")
        self.assertEqual(body["route"]["path"], "/404")
        self.assertEqual(body["metadata"]["resolvedPath"], "/missing")
        self.assertEqual(body["metadata"]["statusCode"], 404)
        self.assertTrue(body["metadata"]["notFound"])
        self.assertEqual(body["i18n"]["lang"], "en")
        self.assertIn("test-prefix/pamelabetancourt.com/not-found/page-config.json", self.loaded_keys)

    def test_unknown_route_uses_404_route_when_not_found_page_id_is_omitted(self):
        self.metadata.pop("notFoundPageId", None)
        for prefix in ("prod-prefix", "test-prefix"):
            self.payloads[f"{prefix}/pamelabetancourt.com/site-config.json"].pop("notFoundPageId", None)

        response = self.handler.lambda_handler(event("test.pamelabetancourt.com", "/missing"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["pageId"], "not-found")
        self.assertEqual(body["route"]["path"], "/404")
        self.assertEqual(body["metadata"]["statusCode"], 404)

    def test_unknown_route_does_not_fall_back_to_default_page_id(self):
        response = self.handler.lambda_handler(event("test.pamelabetancourt.com", "/missing"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertNotEqual(body["pageId"], body["siteConfig"]["defaultPageId"])
        self.assertEqual(body["pageId"], "not-found")

    def test_unknown_route_falls_back_to_canonical_404_when_draft_has_no_404(self):
        self.metadata["routes"] = [{"path": "/", "pageId": "default"}]
        for prefix in ("prod-prefix", "test-prefix"):
            self.put_site(prefix, "pamelabetancourt.com", include_not_found=False)

        response = self.handler.lambda_handler(event("test.pamelabetancourt.com", "/missing", "en"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["domain"], "zoolandingpage.com.mx")
        self.assertEqual(body["environment"], "test")
        self.assertEqual(body["versionId"], "canonical-test-v1")
        self.assertEqual(body["pageId"], "not-found")
        self.assertEqual(body["metadata"]["requestedDomain"], "test.pamelabetancourt.com")
        self.assertEqual(body["metadata"]["fallbackFromDomain"], "pamelabetancourt.com")
        self.assertEqual(body["metadata"]["statusCode"], 404)

    def test_missing_domain_uses_canonical_404(self):
        response = self.handler.lambda_handler(event("missing.example", "/missing", "en"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["domain"], "zoolandingpage.com.mx")
        self.assertEqual(body["environment"], "production")
        self.assertEqual(body["pageId"], "not-found")
        self.assertEqual(body["metadata"]["requestedDomain"], "missing.example")
        self.assertEqual(body["metadata"]["fallbackFromDomain"], "missing.example")
        self.assertEqual(body["metadata"]["statusCode"], 404)

    def test_missing_test_domain_uses_canonical_test_404(self):
        response = self.handler.lambda_handler(event("test.missing.example", "/missing", "en"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["domain"], "zoolandingpage.com.mx")
        self.assertEqual(body["environment"], "test")
        self.assertEqual(body["versionId"], "canonical-test-v1")
        self.assertEqual(body["pageId"], "not-found")
        self.assertEqual(body["metadata"]["requestedDomain"], "test.missing.example")
        self.assertEqual(body["metadata"]["fallbackFromDomain"], "test.missing.example")
        self.assertEqual(body["metadata"]["statusCode"], 404)

    def test_test_alias_falls_back_to_canonical_404_if_no_test_pointer_exists(self):
        self.metadata["publishedEnvironments"].pop("test")
        response = self.handler.lambda_handler(event("test.pamelabetancourt.com", "/missing", "en"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["domain"], "zoolandingpage.com.mx")
        self.assertEqual(body["environment"], "test")
        self.assertEqual(body["versionId"], "canonical-test-v1")
        self.assertEqual(body["metadata"]["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()
