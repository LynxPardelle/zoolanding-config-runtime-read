import unittest
from copy import deepcopy

from catalog_overlay import CatalogOwnership, CatalogSource, merge_catalog_cards


DOMAIN = "catalog.example.test"
SOURCE = f"draft:{DOMAIN}"


def manual_card(card_id, url=None):
    return {
        "id": card_id,
        "title": f"Editorial {card_id}",
        "description": "An existing description.",
        "url": url or f"https://manual.example.test/{card_id}",
        "imageSrc": "https://assets.zoolandingpage.com.mx/catalog/manual.webp",
        "imageAlt": "Editorial cover",
    }


def entry(entry_id, path, kind="app", enabled=True):
    return {
        "entryId": entry_id,
        "kind": kind,
        "path": path,
        "title": f"Published {entry_id}",
        "description": "A published description.",
        "imageUrl": f"https://{DOMAIN}/cover.webp",
        "imageAlt": "Published cover",
        "enabled": enabled,
    }


def projection(*entries, **overrides):
    return {
        "sourceId": SOURCE, "sourceDomain": DOMAIN, "environment": "test", "catalogState": "declared",
        "entries": list(entries), **overrides,
    }


def approved(**ownership):
    return {SOURCE: CatalogSource(DOMAIN, ownership)}


class CatalogOverlayTests(unittest.TestCase):
    def test_missing_source_preserves_manual_cards_and_order(self):
        seed = {"website": [manual_card("website")], "app": [manual_card("three"), manual_card("one")]}
        before = deepcopy(seed)
        owners = approved(one=CatalogOwnership("one", "app", adopt_seed=True))
        for current in ([], [projection(catalogState="legacy")]):
            result = merge_catalog_cards(seed, current, owners, "test")
            self.assertEqual(result, seed)
        result["app"][0]["title"] = "Changed result"
        self.assertEqual(seed, before)

    def test_fourth_product_appears_and_explicit_adoption_preserves_editorial_order(self):
        seed = {"website": [manual_card("website")], "app": [manual_card(i) for i in ["two", "one", "three"]]}
        current = [projection(entry("four", "/four"), entry("first", "/one"), _privateReceipt="internal")]
        owners = approved(first=CatalogOwnership("one", "app", adopt_seed=True), four=CatalogOwnership("four", "app"))
        editorial = {"one": {"title": "Kept headline", "imageSrc": "https://assets.zoolandingpage.com.mx/editorial/cover.webp"}}
        result = merge_catalog_cards(seed, current, owners, "test", editorial)
        self.assertEqual([card["id"] for card in result["app"]], ["two", "one", "three", "four"])
        self.assertEqual(result["app"][1]["title"], "Kept headline")
        self.assertEqual(result["app"][1]["imageSrc"], editorial["one"]["imageSrc"])
        self.assertEqual(result["app"][1]["url"], f"https://{DOMAIN}/one")
        self.assertEqual(result["app"][3]["title"], "Published four")
        self.assertNotIn("_privateReceipt", str(result))
        self.assertEqual(result["website"], seed["website"])

    def test_complete_projection_retires_disabled_and_removed_adopted_entries(self):
        seed = {"app": [manual_card("one"), manual_card("two")]}
        owners = approved(one=CatalogOwnership("one", "app", adopt_seed=True), four=CatalogOwnership("four", "app"))
        for current in [projection(), projection(entry("one", "/one", enabled=False), entry("four", "/four", enabled=False))]:
            with self.subTest(entries=current["entries"]):
                self.assertEqual(merge_catalog_cards(seed, [current], owners, "test")["app"], [seed["app"][1]])

    def test_unknown_source_or_wrong_context_cannot_supply_entries(self):
        sources = approved(one=CatalogOwnership("one", "app"))
        for document in [
            projection(entry("one", "/one"), sourceId="draft:unknown.example.test"),
            projection(entry("one", "/one"), sourceDomain="wrong.example.test"),
            projection(entry("one", "/one"), environment="production"),
            projection(entry("unowned", "/one")),
            projection(entry("one", "/one", kind="website")),
            projection(entry("one", "/one"), catalogState="legacy"),
            projection({**entry("one", "/one"), "imageUrl": "https://wrong.example.test/cover.webp"}),
            projection({**entry("one", "/one"), "title": "Invalid control\u202e"}),
        ]:
            with self.subTest(source=document["sourceId"], environment=document["environment"]):
                with self.assertRaises(ValueError):
                    merge_catalog_cards({}, [document], sources, "test")

    def test_refuses_card_and_url_collisions(self):
        seed = {"app": [manual_card("one", f"https://{DOMAIN}/one/")]}
        for documents, ownership in [
            ([projection(entry("one", "/one"))], approved(one=CatalogOwnership("one", "app"))),
            ([projection(entry("new", "/one"))], approved(new=CatalogOwnership("new", "app"))),
            ([projection(entry("new", "/new")), projection(entry("new", "/new"))], approved(new=CatalogOwnership("new", "app"))),
            ([], approved(one=CatalogOwnership("same", "app"), two=CatalogOwnership("same", "website"))),
        ]:
            with self.assertRaises(ValueError):
                merge_catalog_cards(seed, documents, ownership, "test")

    def test_editorial_can_hide_or_rank_without_claiming_another_destination(self):
        seed = {"app": [manual_card("one"), manual_card("two"), manual_card("three")]}
        editorial = {"one": {"hidden": True}, "three": {"order": 0, "featured": True}}
        result = merge_catalog_cards(seed, [], {}, "test", editorial)["app"]
        self.assertEqual([card["id"] for card in result], ["three", "two"])
        self.assertIs(result[0]["featured"], True)
        self.assertNotIn("order", result[0])
        with self.assertRaises(ValueError):
            merge_catalog_cards(seed, [], {}, "test", {"one": {"url": "https://wrong.example.test/"}})
