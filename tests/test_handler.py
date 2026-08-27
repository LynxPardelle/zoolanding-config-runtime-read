import importlib
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from urllib.parse import unquote


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


SERVER_DESCRIPTOR_FILES = (
    "auth-profile-registry.json",
    "integrations.json",
    "data-spaces.json",
    "commerce.json",
    "integration-bindings.json",
    "notification-policies.json",
)


def decoded_key_segments(key):
    decoded = str(key).replace("\\", "/")
    for _ in range(4):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return [segment.casefold() for segment in decoded.split("/") if segment]


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
        self.content_hub_queries = []
        self.content_hub_item_reads = []

        for prefix in ("prod-prefix", "test-prefix", "dev-prefix"):
            self.put_site(prefix, "pamelabetancourt.com", include_not_found=True)
            self.put_page(prefix, "pamelabetancourt.com", "default", "Hero")
            self.put_page(prefix, "pamelabetancourt.com", "not-found", "Page not found")

        for prefix in ("canonical-prod-prefix", "canonical-test-prefix"):
            self.put_site(prefix, "zoolandingpage.com.mx", include_not_found=True)
            self.put_page(prefix, "zoolandingpage.com.mx", "default", "Canonical hero")
            self.put_page(prefix, "zoolandingpage.com.mx", "not-found", "Canonical 404")

        def load_item(_table, pk, sk="METADATA"):
            if _table in {"content-hub-metadata", "content-hub-metadata-dev", "content-hub-metadata-test", "content-hub-metadata-prod"}:
                self.content_hub_item_reads.append({"tableName": _table, "pk": pk, "sk": sk})
                content_hub_item = next((
                    dict(item)
                    for item in self.content_hub_items
                    if item.get("pk") == pk
                    and item.get("sk") == sk
                    and str(item.get("tableName") or _table) == _table
                ), None)
                return content_hub_item if content_hub_item is not None else self.items.get((pk, sk))
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
                self.owner.content_hub_queries.append({
                    "tableName": self.table_name,
                    "pk": pk,
                    "skPrefix": sk_prefix,
                    "limit": Limit,
                    "exclusiveStartKey": ExclusiveStartKey,
                })
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

    def configure_fixed_language_routes(self):
        routes = [
            {"path": "/soft-landing-china/eng", "pageId": "soft-landing-china", "language": "en"},
            {"path": "/soft-landing-china/zh", "pageId": "soft-landing-china", "language": "zh"},
        ]
        self.metadata["routes"].extend(dict(route) for route in routes)
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["site"] = {
            "i18n": {
                "defaultLanguage": "es",
                "supportedLanguages": [
                    {"code": "es", "label": "ES"},
                    {"code": "en", "label": "EN"},
                    {"code": "zh", "label": "中文"},
                ],
            }
        }
        site_config["routes"].extend(dict(route) for route in routes)
        self.put_page("test-prefix", "pamelabetancourt.com", "soft-landing-china", "China campaign")
        self.put_payload(
            "test-prefix",
            "pamelabetancourt.com",
            "i18n/zh.json",
            {"lang": "zh", "dictionary": {"shared": "共享"}},
        )
        self.put_payload(
            "test-prefix",
            "pamelabetancourt.com",
            "soft-landing-china/i18n/zh.json",
            {"pageId": "soft-landing-china", "lang": "zh", "dictionary": {"title": "中国业务落地"}},
        )

    def configure_fixed_not_found_route(self, language="en"):
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["site"] = {
            "i18n": {
                "defaultLanguage": "es",
                "supportedLanguages": ["es", "en", "zh"],
            }
        }
        metadata_route = next((route for route in self.metadata["routes"] if route["path"] == "/404"), None)
        if metadata_route is None:
            metadata_route = {"path": "/404", "pageId": "not-found", "label": "Not found"}
            self.metadata["routes"].append(metadata_route)
        site_route = next(route for route in site_config["routes"] if route["path"] == "/404")
        metadata_route["language"] = language
        site_route["language"] = language
        self.put_payload(
            "test-prefix",
            "pamelabetancourt.com",
            "i18n/zh.json",
            {"lang": "zh", "dictionary": {"shared": "共享"}},
        )
        self.put_payload(
            "test-prefix",
            "pamelabetancourt.com",
            "not-found/i18n/zh.json",
            {"pageId": "not-found", "lang": "zh", "dictionary": {"title": "未找到页面"}},
        )

    def assert_route_language_failure_is_public_and_generic(self, source, value):
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["site"] = {
            "i18n": {
                "defaultLanguage": "es",
                "supportedLanguages": ["es", "en", "zh"],
            }
        }
        metadata_route = self.metadata["routes"][0]
        site_route = site_config["routes"][0]
        metadata_route.pop("language", None)
        site_route.pop("language", None)
        metadata_route["privateDiagnostics"] = "private-route-language-marker"
        site_route["privateDiagnostics"] = "private-route-language-marker"
        (metadata_route if source == "metadata" else site_route)["language"] = value
        self.loaded_keys.clear()
        output = io.StringIO()

        with redirect_stdout(output):
            response = self.handler.lambda_handler(
                event("api.zoolandingpage.com.mx", domain="pamelabetancourt.com", environment="test"),
                Context(),
            )

        body = parse(response)
        serialized = response["body"] + output.getvalue()
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(body, {"ok": False, "error": "Internal error"})
        self.assertNotIn("private-route-language-marker", serialized)
        self.assertFalse(any("/i18n/" in key for key in self.loaded_keys))
        self.assertEqual(
            self.loaded_keys,
            ["test-prefix/pamelabetancourt.com/site-config.json"],
        )

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

    def test_canonical_domain_environment_query_maps_dev_to_test(self):
        response = self.handler.lambda_handler(
            event("api.zoolandingpage.com.mx", domain="pamelabetancourt.com", environment="dev"),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["environment"], "test")
        self.assertEqual(body["versionId"], "test-v1")
        self.assertTrue(any(key.startswith("test-prefix/") for key in self.loaded_keys))

    def test_runtime_payload_loader_rejects_every_server_descriptor_path_before_s3(self):
        path_templates = (
            "pamelabetancourt.com/server/{name}",
            "pamelabetancourt.com/SERVER/{name}",
            "pamelabetancourt.com/%73erver/{name}",
            "pamelabetancourt.com/%2573erver/{name}",
            "pamelabetancourt.com/public/../server/{name}",
            "pamelabetancourt.com/public/%2e%2e/%73erver/{name}",
            "pamelabetancourt.com\\server\\{name}",
            "pamelabetancourt.com/server/{name}?download=1",
        )

        for descriptor_name in SERVER_DESCRIPTOR_FILES:
            for template in path_templates:
                relative_path = template.format(name=descriptor_name)
                with self.subTest(relative_path=relative_path):
                    self.loaded_keys.clear()
                    with self.assertRaisesRegex(ValueError, "unsafe_runtime_payload_key"):
                        self.handler._load_payload("runtime-bucket", "test-prefix", relative_path)
                    self.assertEqual(self.loaded_keys, [])

    def test_runtime_bundle_rejects_server_segments_from_page_lang_domain_and_paths(self):
        cases = (
            {
                "name": "query-page-id",
                "route_path": "/admin",
                "page_id": "server",
                "request": event("api.zoolandingpage.com.mx", path="/admin", domain="pamelabetancourt.com", environment="test"),
            },
            {
                "name": "encoded-page-id-and-query-path",
                "route_path": "/server%2Fintegrations.json",
                "page_id": "%73erver/private-customer-marker",
                "request": event(
                    "api.zoolandingpage.com.mx",
                    path="/server%2Fintegrations.json",
                    domain="pamelabetancourt.com",
                    environment="test",
                ),
            },
            {
                "name": "double-encoded-page-id-and-raw-path",
                "route_path": "/raw-admin",
                "page_id": "%2573erver/private-customer-marker",
                "request": {
                    "headers": {"host": "api.zoolandingpage.com.mx"},
                    "queryStringParameters": {"domain": "pamelabetancourt.com", "environment": "test", "lang": "es"},
                    "rawPath": "/raw-admin",
                    "requestContext": {"http": {"path": "/raw-admin"}},
                },
            },
            {
                "name": "traversal-page-id",
                "route_path": "/public/../server/commerce.json",
                "page_id": "public/../server/private-customer-marker",
                "request": event(
                    "api.zoolandingpage.com.mx",
                    path="/public/../server/commerce.json",
                    domain="pamelabetancourt.com",
                    environment="test",
                ),
            },
            {
                "name": "backslash-page-id",
                "route_path": "/backslash",
                "page_id": "public\\server\\private-customer-marker",
                "request": event("api.zoolandingpage.com.mx", path="/backslash", domain="pamelabetancourt.com", environment="test"),
            },
            {
                "name": "lang-traversal",
                "route_path": "/",
                "page_id": "default",
                "request": event(
                    "api.zoolandingpage.com.mx",
                    path="/",
                    lang="%252e%252e%252f%2573erver%252fintegrations",
                    domain="pamelabetancourt.com",
                    environment="test",
                ),
            },
        )

        for case in cases:
            with self.subTest(case=case["name"]):
                self.loaded_keys.clear()
                self.metadata["routes"] = [{"path": case["route_path"], "pageId": case["page_id"]}]
                site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
                site_config["routes"] = [{"path": case["route_path"], "pageId": case["page_id"]}]
                output = io.StringIO()
                with redirect_stdout(output):
                    response = self.handler.lambda_handler(case["request"], Context())
                serialized = f"{response['body']}\n{output.getvalue()}"

                self.assertEqual(response["statusCode"], 500)
                self.assertNotIn("private-customer-marker", serialized)
                self.assertNotIn("credential-value-marker", serialized)
                self.assertFalse(
                    any("server" in decoded_key_segments(key) for key in self.loaded_keys),
                    self.loaded_keys,
                )

    def test_runtime_bundle_rejects_encoded_server_domain_and_ignores_invalid_environment(self):
        domain_variants = (
            "tenant.example/server",
            "tenant.example/SERVER",
            "tenant.example/%73erver",
            "tenant.example/%2573erver",
            "tenant.example/public/../server",
            "tenant.example\\server",
        )
        environment_variants = ("server", "%73erver", "%2573erver", "../server", "..\\server")

        for domain_variant in domain_variants:
            malicious_metadata = dict(self.metadata)
            malicious_metadata["published"] = {"versionId": "prod-v1", "prefix": "prod-prefix"}
            self.items[(f"SITE#{domain_variant.casefold()}", "METADATA")] = malicious_metadata
            with self.subTest(domain=domain_variant):
                self.loaded_keys.clear()
                response = self.handler.lambda_handler(event("api.zoolandingpage.com.mx", domain=domain_variant), Context())
                self.assertEqual(response["statusCode"], 500)
                self.assertFalse(
                    any("server" in decoded_key_segments(key) for key in self.loaded_keys),
                    self.loaded_keys,
                )

        for environment_variant in environment_variants:
            with self.subTest(environment=environment_variant):
                self.loaded_keys.clear()
                response = self.handler.lambda_handler(
                    event("api.zoolandingpage.com.mx", domain="pamelabetancourt.com", environment=environment_variant),
                    Context(),
                )
                self.assertEqual(response["statusCode"], 200)
                self.assertEqual(parse(response)["environment"], "production")
                self.assertFalse(any("server" in decoded_key_segments(key) for key in self.loaded_keys))

    def test_runtime_error_does_not_echo_request_or_exception_data(self):
        def fail_resolution(_domain):
            raise RuntimeError("credential-value-marker")

        self.handler._resolve_site_metadata = fail_resolution
        output = io.StringIO()
        request = event(
            "api.zoolandingpage.com.mx",
            path="/private-customer-marker",
            domain="private-customer-marker.example",
            environment="test",
        )

        with redirect_stdout(output):
            response = self.handler.lambda_handler(request, Context())

        body = parse(response)
        serialized = f"{response['body']}\n{output.getvalue()}"
        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(body, {"ok": False, "error": "Internal error"})
        self.assertNotIn("private-customer-marker", serialized)
        self.assertNotIn("credential-value-marker", serialized)

    def test_content_hub_storage_errors_do_not_echo_exception_data(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME = "content-hub-metadata"
        self.handler.CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST = "content-hub-packages-test"

        def fail_table(_table_name):
            raise RuntimeError("private-customer-marker")

        def fail_s3(_bucket, _key):
            raise RuntimeError("credential-value-marker")

        self.handler.get_table = fail_table
        self.handler.load_json_from_s3 = fail_s3
        output = io.StringIO()
        with redirect_stdout(output):
            items = self.handler._query_content_hub_metadata("main", "ARTICLE#", "test")
            bundle = self.handler._load_content_hub_json_bundle(
                "content-hubs/test/main/published/pamelabetancourt.com/es/article-1/revision-1/bundle.json",
                "test",
                "main",
                "pamelabetancourt.com",
                "es",
                "article-1",
            )

        serialized = output.getvalue()
        self.assertEqual(items, [])
        self.assertIsNone(bundle)
        self.assertNotIn("private-customer-marker", serialized)
        self.assertNotIn("credential-value-marker", serialized)

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

    def test_public_route_projection_preserves_validated_language(self):
        projected = self.handler._public_route({
            "path": "/soft-landing-china/eng",
            "pageId": "soft-landing-china",
            "language": "en",
            "privateDiagnostics": "must-not-render",
        })

        self.assertEqual(projected, {
            "path": "/soft-landing-china/eng",
            "pageId": "soft-landing-china",
            "language": "en",
        })

    def test_fixed_route_language_overrides_request_and_keeps_public_bundle_in_agreement(self):
        self.configure_fixed_language_routes()

        for path, conflicting_language, expected_language in (
            ("/soft-landing-china/eng", "zh", "en"),
            ("/soft-landing-china/zh", "en", "zh"),
        ):
            with self.subTest(path=path):
                loaded_before = len(self.loaded_keys)
                response = self.handler.lambda_handler(
                    event(
                        "api.zoolandingpage.com.mx",
                        path=path,
                        lang=conflicting_language,
                        domain="pamelabetancourt.com",
                        environment="test",
                    ),
                    Context(),
                )
                body = parse(response)
                matching_route = next(route for route in body["siteConfig"]["routes"] if route["path"] == path)
                request_keys = self.loaded_keys[loaded_before:]

                self.assertEqual(response["statusCode"], 200)
                self.assertEqual(body["pageId"], "soft-landing-china")
                self.assertEqual(body["lang"], expected_language)
                self.assertEqual(body["i18n"]["lang"], expected_language)
                self.assertEqual(body["route"]["language"], expected_language)
                self.assertEqual(matching_route["language"], expected_language)
                self.assertTrue(any(key.endswith(f"/i18n/{expected_language}.json") for key in request_keys))
                self.assertFalse(any(key.endswith(f"/i18n/{conflicting_language}.json") for key in request_keys))

    def test_language_free_routes_keep_request_then_site_default_precedence(self):
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["site"] = {
            "i18n": {
                "defaultLanguage": "es",
                "supportedLanguages": ["es", "en"],
            }
        }

        explicit_response = self.handler.lambda_handler(
            event(
                "api.zoolandingpage.com.mx",
                lang="en",
                domain="pamelabetancourt.com",
                environment="test",
            ),
            Context(),
        )
        default_response = self.handler.lambda_handler(
            event(
                "api.zoolandingpage.com.mx",
                lang=None,
                domain="pamelabetancourt.com",
                environment="test",
            ),
            Context(),
        )

        self.assertEqual(parse(explicit_response)["lang"], "en")
        self.assertEqual(parse(default_response)["lang"], "es")

    def test_unpublished_future_metadata_route_does_not_break_published_home(self):
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["site"] = {
            "i18n": {
                "defaultLanguage": "es",
                "supportedLanguages": ["es"],
            }
        }
        self.metadata["routes"].extend([
            {"path": "/future", "pageId": "future", "language": "fr"},
            {"path": "/future/:slug", "pageId": "future-detail", "language": "fr"},
        ])
        self.metadata["routes"][0]["language"] = "fr"
        self.metadata["draft"] = {
            "versionId": "future-draft-not-published",
            "prefix": "future-draft-prefix",
        }
        self.loaded_keys.clear()

        response = self.handler.lambda_handler(
            event(
                "api.zoolandingpage.com.mx",
                lang=None,
                domain="pamelabetancourt.com",
                environment="test",
            ),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["versionId"], "test-v1")
        self.assertEqual(body["pageId"], "default")
        self.assertEqual(body["lang"], "es")
        self.assertEqual(body["i18n"]["lang"], "es")
        self.assertEqual(body["route"]["path"], "/")
        self.assertNotIn("/future", {route["path"] for route in body["siteConfig"]["routes"]})
        self.assertFalse(any("/future/" in key or "/future-detail/" in key for key in self.loaded_keys))

    def test_unpublished_future_metadata_paths_do_not_resolve_before_pointer_publish(self):
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["site"] = {
            "i18n": {
                "defaultLanguage": "es",
                "supportedLanguages": ["es"],
            }
        }
        self.metadata["routes"].extend([
            {"path": "/future", "pageId": "future", "language": "fr"},
            {"path": "/future/:slug", "pageId": "future-detail", "language": "fr"},
        ])
        self.metadata["routes"][0]["language"] = "fr"
        self.metadata["draft"] = {
            "versionId": "future-draft-not-published",
            "prefix": "future-draft-prefix",
        }

        for path in ("/future", "/future/item"):
            with self.subTest(path=path):
                self.loaded_keys.clear()
                response = self.handler.lambda_handler(
                    event(
                        "api.zoolandingpage.com.mx",
                        path=path,
                        lang="es",
                        domain="pamelabetancourt.com",
                        environment="test",
                    ),
                    Context(),
                )
                body = parse(response)

                self.assertEqual(response["statusCode"], 200)
                self.assertEqual(body["versionId"], "test-v1")
                self.assertEqual(body["pageId"], "not-found")
                self.assertEqual(body["metadata"]["statusCode"], 404)
                self.assertTrue(body["metadata"]["notFound"])
                self.assertEqual(body["route"]["path"], "/404")
                self.assertNotIn(path, {route["path"] for route in body["siteConfig"]["routes"]})
                self.assertFalse(any("/future/" in key or "/future-detail/" in key for key in self.loaded_keys))

    def test_unpublished_future_metadata_content_hub_is_not_exposed_or_resolved(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["runtime"] = {
            "contentHubs": [{
                "hubId": "main",
                "routeBasePath": "/blog",
                "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                "defaultLocale": "es",
                "locales": ["es"],
                "publicArticles": [],
                "publicTaxonomy": [],
            }]
        }
        self.metadata["defaultPageId"] = "future-default"
        self.metadata["contentHubs"] = [{
            "hubId": "future-hub",
            "name": "Future hub",
            "defaultLanguage": "fr",
            "canonicalDraftDomain": "future.example",
        }]
        self.metadata["draft"] = {
            "versionId": "future-draft-not-published",
            "prefix": "future-draft-prefix",
        }

        response = self.handler.lambda_handler(
            event(
                "api.zoolandingpage.com.mx",
                lang="es",
                domain="pamelabetancourt.com",
                environment="test",
            ),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(
            [hub["hubId"] for hub in body["metadata"]["contentHubs"]],
            ["main"],
        )
        self.assertEqual(
            [hub["hubId"] for hub in body["siteConfig"]["contentHubs"]],
            ["main"],
        )
        self.assertEqual(
            {query["pk"] for query in self.content_hub_queries},
            {"HUB#main"},
        )
        self.assertNotIn("future-hub", response["body"])

    def test_unpublished_future_metadata_default_does_not_drive_legacy_published_home(self):
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config.pop("defaultPageId")
        site_config["routes"] = [
            route
            for route in site_config["routes"]
            if route["path"] != "/"
        ]
        self.metadata["defaultPageId"] = "future-default"
        self.metadata["contentHubs"] = [{
            "hubId": "future-hub",
            "name": "Future hub",
            "defaultLanguage": "fr",
            "canonicalDraftDomain": "future.example",
        }]
        self.metadata["draft"] = {
            "versionId": "future-draft-not-published",
            "prefix": "future-draft-prefix",
        }
        self.loaded_keys.clear()

        response = self.handler.lambda_handler(
            event(
                "api.zoolandingpage.com.mx",
                lang="es",
                domain="pamelabetancourt.com",
                environment="test",
            ),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["versionId"], "test-v1")
        self.assertEqual(body["pageId"], "default")
        self.assertEqual(body["metadata"]["statusCode"], 200)
        self.assertFalse(body["metadata"]["notFound"])
        self.assertFalse(any("/future-default/" in key for key in self.loaded_keys))

    def test_legacy_and_matching_pointer_metadata_keep_derived_fallbacks(self):
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config.pop("defaultPageId")
        site_config.pop("contentHubs")
        site_config["routes"] = [
            route
            for route in site_config["routes"]
            if route["path"] != "/"
        ]
        self.metadata["defaultPageId"] = "metadata-default"
        self.metadata["contentHubs"] = [{
            "hubId": "metadata-hub",
            "name": "Metadata hub",
            "defaultLanguage": "es",
            "canonicalDraftDomain": "pamelabetancourt.com",
        }]
        self.put_page("test-prefix", "pamelabetancourt.com", "metadata-default", "Metadata default")

        for mode, draft_pointer in (
            ("legacy", None),
            ("matching", {"versionId": "test-v1", "prefix": "test-prefix"}),
        ):
            with self.subTest(mode=mode):
                if draft_pointer is None:
                    self.metadata.pop("draft", None)
                else:
                    self.metadata["draft"] = draft_pointer

                response = self.handler.lambda_handler(
                    event(
                        "api.zoolandingpage.com.mx",
                        lang="es",
                        domain="pamelabetancourt.com",
                        environment="test",
                    ),
                    Context(),
                )
                body = parse(response)

                self.assertEqual(response["statusCode"], 200)
                self.assertEqual(body["pageId"], "metadata-default")
                self.assertEqual(
                    [hub["hubId"] for hub in body["metadata"]["contentHubs"]],
                    ["metadata-hub"],
                )

    def test_exact_site_config_route_wins_before_older_metadata_parameter_route(self):
        self.metadata["routes"].append({
            "path": "/soft-landing-china/:locale",
            "pageId": "legacy-parameter-shell",
        })
        self.put_page("test-prefix", "pamelabetancourt.com", "legacy-parameter-shell", "Legacy shell")
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["site"] = {
            "i18n": {"defaultLanguage": "es", "supportedLanguages": ["es", "en", "zh"]}
        }
        site_config["routes"].append({
            "path": "/soft-landing-china/eng",
            "pageId": "soft-landing-china",
            "language": "en",
        })
        self.put_page("test-prefix", "pamelabetancourt.com", "soft-landing-china", "China campaign")

        response = self.handler.lambda_handler(
            event(
                "api.zoolandingpage.com.mx",
                path="/soft-landing-china/eng",
                lang="zh",
                domain="pamelabetancourt.com",
                environment="test",
            ),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["pageId"], "soft-landing-china")
        self.assertEqual(body["route"]["path"], "/soft-landing-china/eng")
        self.assertEqual(body["route"]["language"], "en")
        self.assertEqual(body["lang"], "en")

    def test_older_metadata_route_without_language_is_backfilled_from_exact_site_route(self):
        self.configure_fixed_language_routes()
        metadata_route = next(
            route for route in self.metadata["routes"] if route["path"] == "/soft-landing-china/eng"
        )
        metadata_route.pop("language")

        response = self.handler.lambda_handler(
            event(
                "api.zoolandingpage.com.mx",
                path="/soft-landing-china/eng",
                lang="zh",
                domain="pamelabetancourt.com",
                environment="test",
            ),
            Context(),
        )
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["route"]["language"], "en")
        self.assertEqual(body["lang"], "en")

    def test_final_fixed_not_found_route_overrides_request_before_localized_reads(self):
        self.configure_fixed_not_found_route("en")
        self.loaded_keys.clear()

        response = self.handler.lambda_handler(
            event(
                "api.zoolandingpage.com.mx",
                path="/missing",
                lang="zh",
                domain="pamelabetancourt.com",
                environment="test",
            ),
            Context(),
        )
        body = parse(response)
        public_route = next(route for route in body["siteConfig"]["routes"] if route["path"] == "/404")

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["metadata"]["statusCode"], 404)
        self.assertEqual(body["lang"], "en")
        self.assertEqual(body["i18n"]["lang"], "en")
        self.assertEqual(body["route"]["language"], "en")
        self.assertEqual(public_route["language"], "en")
        self.assertTrue(any(key.endswith("/i18n/en.json") for key in self.loaded_keys))
        self.assertFalse(any(key.endswith("/i18n/zh.json") for key in self.loaded_keys))

    def test_missing_content_hub_paths_recompute_language_from_final_fixed_404(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.configure_fixed_not_found_route("en")
        self.metadata["routes"].extend([
            {"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"},
            {"path": "/blog/:categorySlug", "pageId": "blog-category"},
        ])
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["routes"].extend([
            {"path": "/blog/:categorySlug/:articleSlug", "pageId": "blog-article"},
            {"path": "/blog/:categorySlug", "pageId": "blog-category"},
        ])
        site_config["runtime"] = {
            "contentHubs": [{
                "hubId": "main",
                "routeBasePath": "/blog",
                "articlePathPattern": "/blog/:categorySlug/:articleSlug",
                "defaultLocale": "es",
                "locales": ["es", "en", "zh"],
                "publicArticles": [],
                "publicTaxonomy": [],
            }]
        }
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-article", "Article shell")
        self.put_page("test-prefix", "pamelabetancourt.com", "blog-category", "Category shell")

        for path in ("/blog/web/missing-article", "/blog/missing-category"):
            with self.subTest(path=path):
                self.loaded_keys.clear()
                queries_before = len(self.content_hub_queries)
                response = self.handler.lambda_handler(
                    event(
                        "api.zoolandingpage.com.mx",
                        path=path,
                        lang="zh",
                        domain="pamelabetancourt.com",
                        environment="test",
                    ),
                    Context(),
                )
                body = parse(response)

                self.assertEqual(response["statusCode"], 200)
                self.assertEqual(body["pageId"], "not-found")
                self.assertEqual(body["metadata"]["statusCode"], 404)
                self.assertEqual(body["lang"], "en")
                self.assertEqual(body["i18n"]["lang"], "en")
                self.assertEqual(body["route"]["language"], "en")
                self.assertTrue(any(key.endswith("/i18n/en.json") for key in self.loaded_keys))
                self.assertFalse(any(key.endswith("/i18n/zh.json") for key in self.loaded_keys))
                self.assertEqual(len(self.content_hub_queries) - queries_before, 2)

    def test_language_free_route_preserves_legacy_default_locale_filename_behavior(self):
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]

        for configured_default, expected_runtime_language in (
            ("pt-BR", "pt-br"),
            ("pt_BR", "pt_br"),
        ):
            with self.subTest(configured_default=configured_default):
                site_config["site"] = {
                    "i18n": {
                        "defaultLanguage": configured_default,
                        "supportedLanguages": [configured_default],
                    }
                }
                self.put_payload(
                    "test-prefix",
                    "pamelabetancourt.com",
                    f"i18n/{expected_runtime_language}.json",
                    {"lang": expected_runtime_language, "dictionary": {"shared": "Compartilhado"}},
                )
                self.put_payload(
                    "test-prefix",
                    "pamelabetancourt.com",
                    f"default/i18n/{expected_runtime_language}.json",
                    {"pageId": "default", "lang": expected_runtime_language, "dictionary": {"title": "Início"}},
                )
                self.loaded_keys.clear()

                response = self.handler.lambda_handler(
                    event(
                        "api.zoolandingpage.com.mx",
                        lang=None,
                        domain="pamelabetancourt.com",
                        environment="test",
                    ),
                    Context(),
                )
                body = parse(response)

                self.assertEqual(response["statusCode"], 200)
                self.assertEqual(body["lang"], expected_runtime_language)
                self.assertEqual(body["i18n"]["lang"], expected_runtime_language)
                self.assertTrue(any(key.endswith(f"/i18n/{expected_runtime_language}.json") for key in self.loaded_keys))

    def test_fixed_route_language_requires_trimmed_nonempty_string_page_id(self):
        invalid_page_ids = (None, "", " ", " campaign ", 7, ["campaign"])
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["site"] = {
            "i18n": {"defaultLanguage": "es", "supportedLanguages": ["es", "en"]}
        }

        for source in ("metadata", "site-config"):
            for page_id in invalid_page_ids:
                with self.subTest(source=source, page_id=page_id):
                    self.metadata["routes"] = [{
                        "path": "/",
                        "pageId": "default",
                        "language": "en",
                    }]
                    site_config["routes"] = [{
                        "path": "/",
                        "pageId": "default",
                        "language": "en",
                    }]
                    selected_route = self.metadata["routes"][0] if source == "metadata" else site_config["routes"][0]
                    selected_route["pageId"] = page_id
                    self.loaded_keys.clear()
                    output = io.StringIO()

                    with redirect_stdout(output):
                        response = self.handler.lambda_handler(
                            event(
                                "api.zoolandingpage.com.mx",
                                lang="zh",
                                domain="pamelabetancourt.com",
                                environment="test",
                            ),
                            Context(),
                        )

                    self.assertEqual(response["statusCode"], 500)
                    self.assertEqual(parse(response), {"ok": False, "error": "Internal error"})
                    self.assertFalse(any("/i18n/" in key for key in self.loaded_keys))

    def test_inactive_lifecycle_validates_route_languages_before_fallback(self):
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["site"] = {
            "i18n": {"defaultLanguage": "es", "supportedLanguages": ["es", "en"]}
        }

        for status in ("maintenance", "suspended"):
            for source in ("metadata", "site-config"):
                with self.subTest(status=status, source=source):
                    self.metadata["lifecycle"] = {"status": status}
                    self.metadata["routes"] = [{
                        "path": "/campaign",
                        "pageId": "campaign",
                        "language": "en",
                        "privateDiagnostics": "private-lifecycle-route-marker",
                    }]
                    site_config["routes"] = [{
                        "path": "/campaign",
                        "pageId": "campaign",
                        "language": "en",
                        "privateDiagnostics": "private-lifecycle-route-marker",
                    }]
                    selected_route = self.metadata["routes"][0] if source == "metadata" else site_config["routes"][0]
                    selected_route["language"] = "fr"
                    self.loaded_keys.clear()
                    output = io.StringIO()

                    with redirect_stdout(output):
                        response = self.handler.lambda_handler(
                            event(
                                "api.zoolandingpage.com.mx",
                                path="/campaign",
                                domain="pamelabetancourt.com",
                                environment="test",
                            ),
                            Context(),
                        )

                    serialized = response["body"] + output.getvalue()
                    self.assertEqual(response["statusCode"], 500)
                    self.assertEqual(parse(response), {"ok": False, "error": "Internal error"})
                    self.assertNotIn("private-lifecycle-route-marker", serialized)
                    self.assertFalse(any("/i18n/" in key for key in self.loaded_keys))
                    self.assertEqual(
                        self.loaded_keys,
                        ["test-prefix/pamelabetancourt.com/site-config.json"],
                    )

    def test_invalid_route_languages_fail_closed_before_localized_payload_reads(self):
        invalid_values = (None, "", " ", "EN", "en_US", "en--US", "english", "fr")

        for source in ("metadata", "site-config"):
            for value in invalid_values:
                with self.subTest(source=source, value=value):
                    self.assert_route_language_failure_is_public_and_generic(source, value)

    def test_route_locale_grammar_matches_authoring_contract(self):
        accepted = (
            ("en", "en"),
            ("zh", {"code": "zh"}),
            ("pt-BR", {"code": "PT-br"}),
            ("zh-Hans", "zh-Hans"),
            ("zh-Hans-CN", "zh-Hans-CN"),
            ("es-419", "es-419"),
        )
        for language, supported_entry in accepted:
            with self.subTest(accepted=language):
                site_config = {
                    "site": {"i18n": {"supportedLanguages": [supported_entry]}},
                    "routes": [{"path": "/campaign", "pageId": "campaign", "language": language}],
                }
                self.handler._validate_route_languages(
                    site_config,
                    self.handler._supported_site_languages(site_config),
                )

        rejected = (
            ("", ["en"]),
            (" ", ["en"]),
            (None, ["en"]),
            ("EN", ["EN"]),
            ("en_US", ["en_US"]),
            ("en--US", ["en--US"]),
            ("english", ["english"]),
            ("fr", ["en"]),
        )
        for language, supported_languages in rejected:
            with self.subTest(rejected=language):
                site_config = {
                    "site": {"i18n": {"supportedLanguages": supported_languages}},
                    "routes": [{"path": "/campaign", "pageId": "campaign", "language": language}],
                }
                with self.assertRaises(ValueError):
                    self.handler._validate_route_languages(
                        site_config,
                        self.handler._supported_site_languages(site_config),
                    )

    def test_duplicate_page_language_pairs_fail_closed_in_each_route_source(self):
        site_config = self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]
        site_config["site"] = {
            "i18n": {"defaultLanguage": "es", "supportedLanguages": ["es", "en", "zh"]}
        }

        for source in ("metadata", "site-config"):
            with self.subTest(source=source):
                self.metadata["routes"] = [{"path": "/", "pageId": "default"}]
                site_config["routes"] = [{"path": "/", "pageId": "default"}]
                duplicate_routes = [
                    {"path": "/soft-landing-china/eng", "pageId": "soft-landing-china", "language": "en"},
                    {"path": "/soft-landing-china/en", "pageId": "soft-landing-china", "language": "en"},
                ]
                if source == "metadata":
                    self.metadata["routes"].extend(duplicate_routes)
                    site_config["routes"].extend([
                        {"path": route["path"], "pageId": route["pageId"]}
                        for route in duplicate_routes
                    ])
                else:
                    site_config["routes"].extend(duplicate_routes)
                self.loaded_keys.clear()

                response = self.handler.lambda_handler(
                    event(
                        "api.zoolandingpage.com.mx",
                        domain="pamelabetancourt.com",
                        environment="test",
                    ),
                    Context(),
                )

                self.assertEqual(response["statusCode"], 500)
                self.assertEqual(parse(response), {"ok": False, "error": "Internal error"})
                self.assertFalse(any("/i18n/" in key for key in self.loaded_keys))

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

    def test_runtime_bundle_preserves_public_draft_font_faces(self):
        fonts = [
            {"family": family, "src": f"/assets/example.com/fonts/{file}.woff2", "weight": weight, "style": "normal"}
            for family, file, weight in (
                ("Newsreader", "newsreader-400", "400"),
                ("Newsreader", "newsreader-500", "500"),
                ("Open Sans", "open-sans-400", "400"),
                ("Open Sans", "open-sans-600", "600"),
            )
        ]
        self.payloads["test-prefix/pamelabetancourt.com/site-config.json"]["site"] = {"fonts": fonts}

        response = self.handler.lambda_handler(event("test.pamelabetancourt.com"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body.get("siteConfig", {}).get("site", {}).get("fonts"), fonts)
        self.assertEqual(body["versionId"], "test-v1")
        self.assertFalse(any(key.endswith(".woff2") for key in self.loaded_keys))

    def test_public_site_config_is_deny_by_default_for_runtime_branches(self):
        projected = self.handler._public_site_config({
            "version": 1,
            "domain": "example.com",
            "routes": [{"path": "/", "pageId": "default"}],
            "site": {
                "appIdentity": {"name": "Example"},
                "privateData": {"customerTaxId": "must-not-render"},
            },
            "defaults": {
                "brand": {"displayName": "Example"},
                "password": "must-not-render",
                "apiKey": "must-not-render",
                "customerTaxId": "must-not-render",
            },
            "privateTopLevel": {"credential": "must-not-render"},
            "runtime": {
                "features": {"debugMode": False},
                "auth": {
                    "enabled": True,
                    "session": {
                        "csrfCookieName": "zlp_csrf",
                        "challengeCsrfCookieName": "zlp_challenge_csrf",
                        "mfaEnrollCsrfCookieName": "zlp_mfa_enroll_csrf",
                        "csrfHeaderName": "X-ZLP-CSRF",
                    },
                },
                "authRemote": {
                    "enabled": True,
                    "authProfileId": "main",
                    "endpoint": "/auth",
                    "credentials": {"apiKey": "must-not-render"},
                },
                "dataSources": [{
                    "id": "catalog",
                    "kind": "api-proxy",
                    "proxySourceId": "catalog",
                    "target": "remote.catalog",
                    "input": {"query": {"source": "literal", "fallback": None}},
                    "mapper": {
                        "itemsPath": "items",
                        "fields": {"mfaSoftwareTokenEnabled": "mfaSoftwareTokenEnabled"},
                    },
                    "credentials": {"apiKey": "must-not-render"},
                    "upstreamHeaders": {"Authorization": "must-not-render"},
                    "internalPolicy": {"privateData": "must-not-render"},
                }],
                "apiActions": [{
                    "id": "save",
                    "kind": "api-proxy",
                    "proxyActionId": "save",
                    "internalPolicy": {"password": "must-not-render"},
                }],
                "integrations": [{"serverOnly": {"token": "must-not-render"}}],
                "contentHubs": [{
                    "hubId": "main",
                    "routeBasePath": "/blog",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "analyticsContext": {"piiPolicy": "aggregate-only"},
                    "serverPolicy": {"credential": "must-not-render"},
                }],
            },
        })

        self.assertEqual(projected["runtime"]["features"], {"debugMode": False})
        self.assertIsNone(projected["runtime"]["dataSources"][0]["input"]["query"]["fallback"])
        self.assertEqual(projected["runtime"]["auth"]["session"]["csrfCookieName"], "zlp_csrf")
        self.assertEqual(projected["runtime"]["auth"]["session"]["challengeCsrfCookieName"], "zlp_challenge_csrf")
        self.assertEqual(projected["runtime"]["auth"]["session"]["mfaEnrollCsrfCookieName"], "zlp_mfa_enroll_csrf")
        self.assertEqual(projected["runtime"]["auth"]["session"]["csrfHeaderName"], "X-ZLP-CSRF")
        self.assertEqual(
            projected["runtime"]["dataSources"][0]["mapper"]["fields"]["mfaSoftwareTokenEnabled"],
            "mfaSoftwareTokenEnabled",
        )
        self.assertEqual(projected["runtime"]["contentHubs"][0]["analyticsContext"]["piiPolicy"], "aggregate-only")
        self.assertNotIn("privateTopLevel", projected)
        self.assertNotIn("integrations", projected["runtime"])
        self.assertNotIn("serverPolicy", projected["runtime"]["contentHubs"][0])
        self.assertNotIn("must-not-render", json.dumps(projected))

    def test_sensitive_public_key_exceptions_are_limited_to_contract_contexts(self):
        sanitized = self.handler._public_content_hub_payload({
            "mfaSoftwareTokenEnabled": "must-not-render",
            "piiPolicy": "must-not-render",
            "csrfCookieName": "must-not-render",
            "challengeCsrfCookieName": "must-not-render",
            "mfaEnrollCsrfCookieName": "must-not-render",
            "csrfHeaderName": "must-not-render",
            "form": {
                "fields": {
                    "mfaSoftwareTokenEnabled": "must-not-render",
                },
            },
            "variables": {
                "analyticsContext": {"piiPolicy": "must-not-render"},
            },
            "mapper": {
                "fields": {
                    "MFA-software-token-enabled": "must-not-render",
                },
            },
            "analyticsContext": {"PII-POLICY": "must-not-render"},
        })
        projected = self.handler._project_public_runtime({
            "dataSources": [{
                "id": "account",
                "mapper": {
                    "fields": {
                        "mfaSoftwareTokenEnabled": {"path": "mfa.softwareTokenEnabled"},
                    },
                },
            }],
            "contentHubs": [{
                "hubId": "main",
                "analyticsContext": {"piiPolicy": "no-pii"},
            }],
        })

        self.assertNotIn("must-not-render", json.dumps(sanitized))
        self.assertEqual(
            projected["dataSources"][0]["mapper"]["fields"]["mfaSoftwareTokenEnabled"],
            {"path": "mfa.softwareTokenEnabled"},
        )
        self.assertEqual(projected["contentHubs"][0]["analyticsContext"]["piiPolicy"], "no-pii")

    def test_sensitive_public_keys_block_legacy_concatenated_spellings(self):
        sensitive_keys = (
            "apikey",
            "privatekey",
            "privatedata",
            "serveronly",
            "serverpolicy",
            "internalpolicy",
            "authheader",
            "upstreamheaders",
            "tablename",
            "bucketname",
            "lambdaarn",
            "groupstoroles",
            "signedurl",
            "tenantid",
            "customertaxid",
            "customerrfc",
            "clientrfc",
            "taxpayerrfc",
            "rfccustomer",
            "customercurp",
            "taxid",
            "bankaccount",
            "bankclabe",
            "routingnumber",
            "cardnumber",
            "awsaccess",
        )
        sanitized = self.handler._public_content_hub_payload({
            key: "must-not-render"
            for key in sensitive_keys
        })

        self.assertEqual(sanitized, {})

    def test_published_bundle_sanitizes_top_level_route_and_lifecycle(self):
        self.metadata["routes"][0]["serverOnly"] = {"credentialRef": "must-not-render"}
        self.metadata["lifecycle"]["serverPolicy"] = {"token": "must-not-render"}

        response = self.handler.lambda_handler(event("test.pamelabetancourt.com"), Context())
        body = parse(response)
        serialized = json.dumps(body)

        self.assertEqual(response["statusCode"], 200)
        self.assertNotIn("serverOnly", serialized)
        self.assertNotIn("serverPolicy", serialized)
        self.assertNotIn("must-not-render", serialized)

    def test_ordinary_route_does_not_attempt_content_hub_article_bundle_lookup(self):
        with patch.object(self.handler, "_content_hub_bundle_for_path", return_value=None) as lookup:
            response = self.handler.lambda_handler(event("test.pamelabetancourt.com"), Context())

        self.assertEqual(response["statusCode"], 200)
        lookup.assert_not_called()

    def test_lifecycle_fallback_sanitizes_site_config_before_returning_it(self):
        bundle = self.handler._fallback_bundle(
            "example.com",
            "maintenance",
            {
                "aliases": ["example.com"],
                "routes": [{
                    "path": "/",
                    "pageId": "maintenance",
                    "serverOnly": {"credentialRef": "must-not-render"},
                }],
            },
            {
                "status": "maintenance",
                "message": "Scheduled maintenance",
                "serverPolicy": {"token": "must-not-render"},
            },
        )

        serialized = json.dumps(bundle["siteConfig"])
        self.assertNotIn("serverOnly", serialized)
        self.assertNotIn("serverPolicy", serialized)
        self.assertNotIn("must-not-render", serialized)

    def test_lifecycle_fallback_removes_fixed_languages_from_english_only_routes(self):
        bundle = self.handler._fallback_bundle(
            "example.com",
            "maintenance",
            {
                "aliases": ["example.com"],
                "routes": [
                    {"path": "/campaign/eng", "pageId": "campaign", "language": "en"},
                    {"path": "/campaign/zh", "pageId": "campaign", "language": "zh"},
                ],
            },
            {"status": "maintenance"},
        )

        self.assertEqual(bundle["siteConfig"]["site"]["i18n"]["supportedLanguages"], ["en"])
        self.assertTrue(bundle["siteConfig"]["routes"])
        self.assertTrue(all("language" not in route for route in bundle["siteConfig"]["routes"]))

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

    def test_runtime_bundle_requires_current_public_metadata_before_using_slug_pointer(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.handler.CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST = "content-hub-packages-test"
        article_path = "/blog/web/qa-e2e"
        bundle_key = "content-hubs/test/main/published/pamelabetancourt.com/es/art_public/rev_1/bundle.json"
        site_config = {
            "domain": "pamelabetancourt.com",
            "runtime": {
                "contentHubs": [{
                    "hubId": "main",
                    "defaultLocale": "es",
                    "locales": ["es"],
                    "publicArticles": [{"articleId": "art_public", "path": article_path}],
                }],
            },
        }
        self.content_hub_items = [{
            "tableName": "content-hub-metadata-test",
            "pk": "HUB#main",
            "sk": "ARTICLE#art_public",
            "articleId": "art_public",
            "status": "draft",
            "visibility": "private",
            "primaryLocale": "es",
            "path": article_path,
        }]
        self.items[("SLUG#test#pamelabetancourt.com#es", f"PATH#{article_path}")] = {
            "articleId": "art_public",
            "path": article_path,
            "publishedBundleKey": bundle_key,
        }
        self.package_payloads[bundle_key] = {
            "articleId": "art_public",
            "path": article_path,
            "status": "published",
            "components": [{"id": "stalePrivateBody", "type": "text"}],
        }

        bundle = self.handler._content_hub_bundle_for_path(site_config, article_path, "es", "test")

        self.assertIsNone(bundle)
        self.assertNotIn(bundle_key, self.loaded_keys)

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
        article_queries = [
            query for query in self.content_hub_queries
            if query["pk"] == "HUB#main" and query["skPrefix"] == "ARTICLE#"
        ]
        self.assertEqual(len(article_queries), 1)
        self.assertEqual(
            [read for read in self.content_hub_item_reads if read["pk"] == "HUB#main"],
            [{
                "tableName": "content-hub-metadata-test",
                "pk": "HUB#main",
                "sk": "ARTICLE#art_public",
            }],
        )

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

    def test_content_hub_metadata_query_caps_total_items_and_final_page_size(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        self.content_hub_items = [
            {
                "tableName": "content-hub-metadata-test",
                "pk": "HUB#main",
                "sk": f"ARTICLE#art_{index:03d}",
                "articleId": f"art_{index:03d}",
            }
            for index in range(401)
        ]

        items = self.handler._query_content_hub_metadata("main", "ARTICLE#", "test")

        self.assertEqual(len(items), 400)
        self.assertEqual([query["limit"] for query in self.content_hub_queries], [200, 200])

    def test_content_hub_runtime_indexes_cap_hubs_per_request(self):
        self.handler.CONTENT_HUB_METADATA_TABLE_NAME_TEST = "content-hub-metadata-test"
        site_config = {
            "runtime": {
                "contentHubs": [
                    {
                        "hubId": f"hub-{index}",
                        "routeBasePath": f"/blog-{index}",
                        "defaultLocale": "es",
                        "locales": ["es"],
                    }
                    for index in range(5)
                ]
            }
        }

        enriched = self.handler._merge_content_hub_runtime_indexes(site_config, "es", "test")
        projected = self.handler._public_site_config(enriched)

        self.assertEqual(len(projected["runtime"]["contentHubs"]), 4)
        self.assertEqual(len(self.content_hub_queries), 8)
        self.assertEqual(
            {query["pk"] for query in self.content_hub_queries},
            {f"HUB#hub-{index}" for index in range(4)},
        )

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
