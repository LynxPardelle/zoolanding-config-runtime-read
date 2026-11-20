from contextlib import nullcontext
import hashlib
import json
import unittest
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

import lambda_function as runtime
from catalog_overlay import CatalogOwnership, CatalogSource


DOMAIN = "zoositioweb.com.mx"
HUB = "zooberiahsystems.com"
SOURCE_ID = f"draft:{DOMAIN}"
CARD_ID = "zoositioweb-com-mx"
ENVIRONMENT = "test"


def card(card_id, domain):
    return {"id": card_id, "title": "Manual site", "description": "From the authored catalog",
            "url": f"https://{domain}/", "imageSrc": "https://assets.zoolandingpage.com.mx/catalog/manual.webp",
            "imageAlt": "Manual cover", "category": "plataformas", "categoryLabel": "Plataformas digitales",
            "searchText": "Editorial aliases"}


def entry(*, kind="website", entry_id=CARD_ID, enabled=True):
    return {"entryId": entry_id, "kind": kind, "path": "/", "title": "New site title", "description": "New published content",
            "imageUrl": f"https://{DOMAIN}/cover.webp", "imageAlt": "New cover", "category": "plataformas", "enabled": enabled}


def document(entries, *, version="v2", environment=ENVIRONMENT):
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    prefix = f"versions/{DOMAIN}/{version}"
    revision = {"schemaVersion": Decimal(1), "sequence": Decimal(2), "entriesSha256": digest, "entryCount": Decimal(len(entries))}
    projection = {"pk": f"CATALOG#{environment}", "sk": f"SOURCE#DRAFT#{DOMAIN}", "sourceId": SOURCE_ID,
                  "sourceDomain": DOMAIN, "environment": environment, "versionId": version, "prefix": prefix,
                  "catalogState": "declared", "entries": entries, **revision}
    pointer = {"versionId": version, "prefix": prefix, "catalogRevision": revision}
    metadata = {"domain": DOMAIN, "revision": Decimal(3), "publishedEnvironments": {environment: pointer}}
    if environment == "production":
        metadata["published"] = pointer
    return projection, metadata


class CatalogDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.manual = [card("landing", "other.example.test"), card(CARD_ID, DOMAIN)]

    def bundle(self, projection, metadata, *, kind="website", domain=HUB, environment=ENVIRONMENT, stack=ENVIRONMENT, sources=None):
        page_id, variable, loop_id = {
            "website": ("sitios-web", "catalog", "landingCards"),
            "app": ("productos", "products", "productsList"),
        }[kind]
        path = f"/{page_id}"
        manual = deepcopy(self.manual)
        page_config = {"pageId": page_id, "rootIds": [loop_id], "structuredData": {"entries": [
            {"@type": "CollectionPage", "mainEntity": {"@type": "ItemList", "itemListElement": [
                {"@type": "ListItem", "position": i, "name": item["title"], "url": item["url"]}
                for i, item in enumerate(manual, 1)
            ]}},
            {"@type": "BreadcrumbList", "itemListElement": []},
        ]}, "analytics": {"sectionIds": [page_id, *[item["id"] for item in manual]]}}
        payloads = {"siteConfig": {"domain": domain}, "pageConfig": page_config,
                    "sharedVariables": None, "pageVariables": {"variables": {variable: {"items": manual}}},
                    "sharedComponents": None, "pageComponents": {"components": [
                        {"id": loop_id, "type": "container", "loopConfig": {"source": "var", "path": f"{variable}.items"}},
                    ]}, "sharedAngoraCombos": None, "pageAngoraCombos": None,
                    "sharedI18n": None, "pageI18n": None}
        with patch.dict(runtime.os.environ, {"ENVIRONMENT_NAME": stack}), patch.object(runtime, "get_table") as get_table:
            get = get_table.return_value.get_item
            def fetch(Key, ConsistentRead):
                self.assertIs(ConsistentRead, True)
                return {"Item": projection if Key["pk"].startswith("CATALOG#") else metadata}
            get.side_effect = fetch
            registration = nullcontext() if sources is None else patch("catalog_overlay.CATALOG_SOURCES", {environment: sources})
            with registration:
                bundle = runtime._published_bundle(
                    request_id="local", requested_domain=domain, domain=domain, resolved_alias=None, environment=environment,
                    version_id="hub", prefix="hub/", path=path, lang="es", lifecycle={}, site_metadata={},
                    route={"path": path, "pageId": page_id}, page_id=page_id, payloads=payloads)
            return bundle, get.call_count

    def test_verified_website_updates_cards_search_and_the_same_item_list(self):
        projection, metadata = document([entry()])
        bundle, reads = self.bundle(projection, metadata)
        self.assertEqual(reads, 2)
        items = bundle["variables"]["variables"]["catalog"]["items"]
        self.assertEqual([item["id"] for item in items], ["landing", CARD_ID])
        self.assertEqual(items[1]["title"], "New site title")
        self.assertIn("New site title", items[1]["searchText"])
        self.assertIn(DOMAIN, items[1]["searchText"])
        self.assertEqual(items[0], self.manual[0])
        list_items = bundle["pageConfig"]["structuredData"]["entries"][0]["mainEntity"]["itemListElement"]
        self.assertEqual(list_items[1], {"@type": "ListItem", "position": 2, "name": items[1]["title"], "url": items[1]["url"]})
        self.assertNotIn("entriesSha256", json.dumps(bundle))

    def test_production_adopts_only_the_registered_zoositioweb_card(self):
        projection, metadata = document([entry()], environment="production")
        options = {"environment": "production", "stack": "prod"}
        bundle, reads = self.bundle(projection, metadata, **options)
        self.assertEqual(reads, 2)
        items = bundle["variables"]["variables"]["catalog"]["items"]
        self.assertEqual([item["id"] for item in items], ["landing", CARD_ID])
        self.assertEqual(items[0], self.manual[0])
        self.assertEqual(items[1]["description"], "New published content")
        entries = bundle["pageConfig"]["structuredData"]["entries"][0]["mainEntity"]["itemListElement"]
        self.assertEqual(sum(item["url"] == f"https://{DOMAIN}/" for item in entries), 1)

        replay, _ = self.bundle(projection, metadata, **options)
        self.assertEqual(replay, bundle)

        unregistered, registry = document([entry(entry_id="unregistered-site")], environment="production")
        rejected, _ = self.bundle(unregistered, registry, **options)
        self.assertEqual(rejected["variables"]["variables"]["catalog"]["items"], self.manual)

    def test_disabled_and_missing_projections_have_distinct_outcomes(self):
        projection, metadata = document([entry(enabled=False)])
        bundle, _ = self.bundle(projection, metadata)
        self.assertEqual(bundle["variables"]["variables"]["catalog"]["items"], self.manual[:1])
        self.assertEqual(len(bundle["pageConfig"]["structuredData"]["entries"][0]["mainEntity"]["itemListElement"]), 1)
        fallback, _ = self.bundle(None, metadata)
        self.assertEqual(fallback["variables"]["variables"]["catalog"]["items"], self.manual)

    def test_stale_tampered_cross_stack_and_unrelated_domain_fall_back(self):
        projection, metadata = document([entry()])
        _, stale = document([entry()], version="v3")
        candidate = deepcopy(projection)
        candidate["entries"][0]["title"] = "Tampered entry"
        for invalid, registry, kwargs in [
            (projection, stale, {}), (candidate, metadata, {}),
            (projection, metadata, {"stack": "prod"}), (projection, metadata, {"domain": "other.example.test"}),
        ]:
            with self.subTest(kwargs=kwargs, version=registry["publishedEnvironments"]["test"]["versionId"]):
                bundle, reads = self.bundle(invalid, registry, **kwargs)
                self.assertEqual(bundle["variables"]["variables"]["catalog"]["items"], self.manual)
                if kwargs:
                    self.assertEqual(reads, 0)

    def test_new_product_is_added_to_variables_schema_and_analytics(self):
        self.manual = [card("roadmap2u", "roadmap2u.com"), card("despensa-lista", "despensalista.com"),
                       card("gtr-lab", "example.test")]
        source = CatalogSource(DOMAIN, {"product-four": CatalogOwnership("product-four", "app")})
        projection, metadata = document([entry(kind="app", entry_id="product-four")])
        bundle, _ = self.bundle(projection, metadata, kind="app", sources={SOURCE_ID: source})
        items = bundle["variables"]["variables"]["products"]["items"]
        self.assertEqual([item["id"] for item in items], ["roadmap2u", "despensa-lista", "gtr-lab", "product-four"])
        self.assertEqual(bundle["pageConfig"]["analytics"]["sectionIds"], ["productos", *[item["id"] for item in items]])
        self.assertEqual(len(bundle["pageConfig"]["structuredData"]["entries"][0]["mainEntity"]["itemListElement"]), 4)


if __name__ == "__main__":
    unittest.main()
