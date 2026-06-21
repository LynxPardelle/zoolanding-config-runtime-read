import importlib
import json
import unittest


class Context:
    aws_request_id = "runtime-request"


def parse(response):
    return json.loads(response["body"])


def event(host, path="/", lang="es", **query):
    query_params = {"path": path, "lang": lang}
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
        self.loaded_keys = []

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

        def load_json(_bucket, key):
            self.loaded_keys.append(key)
            return self.payloads.get(key)

        self.handler.load_item = load_item
        self.handler.load_json_from_s3 = load_json

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
