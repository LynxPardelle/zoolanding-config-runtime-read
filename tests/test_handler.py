import importlib
import json
import unittest


class Context:
    aws_request_id = "runtime-request"


def parse(response):
    return json.loads(response["body"])


def event(host):
    return {
        "headers": {"host": host},
        "queryStringParameters": {"path": "/", "lang": "es"},
        "requestContext": {"http": {"path": "/"}},
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
            "lifecycle": {"status": "active"},
            "published": {"versionId": "prod-v1", "prefix": "prod-prefix"},
            "publishedEnvironments": {
                "production": {"versionId": "prod-v1", "prefix": "prod-prefix"},
                "test": {"versionId": "test-v1", "prefix": "test-prefix"},
            },
        }
        self.items = {
            ("SITE#pamelabetancourt.com", "METADATA"): self.metadata,
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
        self.loaded_keys = []

        def load_item(_table, pk, sk="METADATA"):
            return self.items.get((pk, sk))

        def load_json(_bucket, key):
            self.loaded_keys.append(key)
            if key.endswith("/site-config.json"):
                return {"domain": "pamelabetancourt.com", "routes": [{"path": "/", "pageId": "default"}]}
            if key.endswith("/page-config.json"):
                return {"pageId": "default", "rootIds": ["hero"]}
            if key.endswith("/components.json"):
                return {"components": [{"id": "hero", "type": "text", "config": {"text": "Hero"}}]}
            return None

        self.handler.load_item = load_item
        self.handler.load_json_from_s3 = load_json

    def test_test_alias_uses_test_published_pointer(self):
        response = self.handler.lambda_handler(event("test.pamelabetancourt.com"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["environment"], "test")
        self.assertEqual(body["versionId"], "test-v1")
        self.assertTrue(any(key.startswith("test-prefix/") for key in self.loaded_keys))

    def test_production_alias_uses_production_pointer(self):
        response = self.handler.lambda_handler(event("pamelabetancourt.com"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(body["environment"], "production")
        self.assertEqual(body["versionId"], "prod-v1")
        self.assertTrue(any(key.startswith("prod-prefix/") for key in self.loaded_keys))

    def test_test_alias_fails_if_no_test_pointer_exists(self):
        self.metadata["publishedEnvironments"].pop("test")
        response = self.handler.lambda_handler(event("test.pamelabetancourt.com"), Context())
        body = parse(response)

        self.assertEqual(response["statusCode"], 404)
        self.assertEqual(body["environment"], "test")


if __name__ == "__main__":
    unittest.main()
