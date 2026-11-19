"""Pure catalog merge. The caller supplies trusted ownership and verified source snapshots."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import re
import unicodedata
from urllib.parse import unquote, urlsplit


KINDS = ("website", "app")
ASSET_HOST = "assets.zoolandingpage.com.mx"
HOST_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOST = re.compile(rf"{HOST_LABEL}(?:\.{HOST_LABEL})*")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PATH_SEGMENT = re.compile(r"[A-Za-z0-9._~-]+")
REQUIRED_ENTRY_FIELDS = frozenset({"entryId", "kind", "path", "title", "description", "imageUrl", "imageAlt", "enabled"})
OPTIONAL_ENTRY_FIELDS = frozenset({"category", "builtWith"})
EDITORIAL_FIELDS = frozenset({
    "title", "description", "imageSrc", "imageAlt", "category", "categoryLabel", "searchText",
    "eyebrow", "linkLabel", "featured", "hidden", "order",
})


@dataclass(frozen=True)
class CatalogOwnership:
    card_id: str
    kind: str
    adopt_seed: bool = False


@dataclass(frozen=True)
class CatalogSource:
    domain: str
    entries: Mapping[str, CatalogOwnership]


def _slug(value: object, limit: int) -> bool:
    return isinstance(value, str) and len(value) <= limit and SLUG.fullmatch(value) is not None


def _static_path(value: object) -> bool:
    if value == "/":
        return True
    return isinstance(value, str) and len(value) <= 256 and value.startswith("/") and all(
        segment not in {".", ".."} and PATH_SEGMENT.fullmatch(segment)
        for segment in value[1:].split("/")
    )


def _has_control(value: str) -> bool:
    return any(unicodedata.category(char) in ("Cc", "Cf", "Cs") for char in value)


def _plain_text(value: object, limit: int) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= limit and value.strip() == value
            and unicodedata.normalize("NFC", value) == value and "<" not in value and ">" not in value
            and not _has_control(value))


def _https_url(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or not value.startswith("https://") or len(value) > 1024:
        raise ValueError("Catalog URL must be a public HTTPS URL")
    if _has_control(value) or any(char.isspace() or char in "\\?#" for char in value):
        raise ValueError("Catalog URL has an unsupported character")
    parsed = urlsplit(value)
    host = parsed.netloc.lower()
    if HOST.fullmatch(host) is None:
        raise ValueError("Catalog URL must use a DNS hostname without a port or credentials")
    return host, parsed.path


def _public_card(entry: Mapping, owner: CatalogOwnership, domain: str) -> dict:
    if not REQUIRED_ENTRY_FIELDS <= entry.keys() <= REQUIRED_ENTRY_FIELDS | OPTIONAL_ENTRY_FIELDS:
        raise ValueError("Unexpected projected catalog fields")
    if entry["kind"] != owner.kind or not _static_path(entry["path"]) or type(entry["enabled"]) is not bool:
        raise ValueError("Projected catalog entry is outside its approved scope")
    if not all(_plain_text(entry[field], limit) for field, limit in (("title", 100), ("description", 320), ("imageAlt", 200))):
        raise ValueError("Invalid projected catalog display fields")
    if _https_url(entry["imageUrl"])[0] not in {domain, ASSET_HOST}:
        raise ValueError("Projected catalog cover is outside its approved scope")
    if "category" in entry and not _slug(entry["category"], 48):
        raise ValueError("Invalid projected catalog category")
    if "builtWith" in entry and entry["builtWith"] not in ("zoolandingpage", "zoositioweb"):
        raise ValueError("Invalid projected catalog platform")
    return {
        "id": owner.card_id,
        "title": entry["title"],
        "description": entry["description"],
        "url": f"https://{domain}{entry['path']}",
        "imageSrc": entry["imageUrl"],
        "imageAlt": entry["imageAlt"],
        **{field: entry[field] for field in ("category", "builtWith") if field in entry},
    }


def _validate_editorial(overrides: Mapping, known_ids: set[str]) -> None:
    for card_id, fields in overrides.items():
        if card_id not in known_ids or not isinstance(fields, Mapping) or fields.keys() - EDITORIAL_FIELDS:
            raise ValueError("Editorial catalog override is outside its approved scope")
        for name, value in fields.items():
            expected = {"featured": bool, "hidden": bool, "order": int}.get(name, str)
            if type(value) is not expected:
                raise ValueError("Invalid editorial catalog override value")
        if "imageSrc" in fields:
            _https_url(fields["imageSrc"])


def merge_catalog_cards(
    seed: Mapping[str, Sequence[dict]],
    projections: Sequence[Mapping],
    approved_sources: Mapping[str, CatalogSource],
    environment: str,
    editorial: Mapping[str, Mapping] | None = None,
) -> dict[str, list[dict]]:
    """Preserve seed order, apply complete declared snapshots, and append new cards deterministically.

    Missing and legacy snapshots preserve manually authored seeds. A declared snapshot
    replaces its owner's adopted entries, including explicit disabling and omission.
    The loader must select the current verified snapshot per source and environment.
    Invalid input raises ValueError so the caller can serve its last approved collection.
    """
    if environment not in ("test", "production") or seed.keys() - set(KINDS):
        raise ValueError("Invalid catalog environment or seed kind")
    editorial = editorial or {}
    cards: dict[str, tuple[str, dict]] = {}
    for kind in KINDS:
        for card in seed.get(kind, ()):
            if not isinstance(card, dict):
                raise ValueError("Invalid manual catalog card")
            card_id = card.get("id")
            if not isinstance(card_id, str) or not card_id or card_id in cards:
                raise ValueError("Duplicate or missing manual catalog ID")
            cards[card_id] = (kind, deepcopy(card))

    owned_ids: set[str] = set()
    for source in approved_sources.values():
        if HOST.fullmatch(source.domain) is None:
            raise ValueError("Invalid approved catalog source domain")
        for entry_id, owner in source.entries.items():
            if (not _slug(entry_id, 64) or owner.kind not in KINDS or not owner.card_id
                    or owner.card_id in owned_ids):
                raise ValueError("Duplicate or invalid approved catalog ownership")
            manual = cards.get(owner.card_id)
            if owner.adopt_seed != (manual is not None) or (manual and manual[0] != owner.kind):
                raise ValueError("Catalog ownership cannot replace that seed")
            owned_ids.add(owner.card_id)
    _validate_editorial(editorial, set(cards) | owned_ids)

    seen_sources: set[str] = set()
    updates: dict[str, tuple[str, dict] | None] = {}
    for snapshot in projections:
        if not isinstance(snapshot, Mapping):
            raise ValueError("Invalid catalog snapshot")
        source_id = snapshot.get("sourceId")
        source = approved_sources.get(source_id) if isinstance(source_id, str) else None
        if (source is None or source_id in seen_sources or snapshot.get("sourceDomain") != source.domain
                or snapshot.get("environment") != environment):
            raise ValueError("Unapproved or duplicate catalog snapshot")
        seen_sources.add(source_id)
        entries = snapshot.get("entries")
        state = snapshot.get("catalogState")
        if not isinstance(entries, list) or len(entries) > 32 or state not in ("declared", "legacy"):
            raise ValueError("Invalid catalog snapshot")
        if state == "legacy":
            if entries:
                raise ValueError("A legacy catalog snapshot cannot contain entries")
            continue

        for owner in source.entries.values():
            if owner.adopt_seed:
                updates[owner.card_id] = None
        seen_entries: set[str] = set()
        seen_paths: set[str] = set()
        for entry in entries:
            entry_id = entry.get("entryId") if isinstance(entry, Mapping) else None
            owner = source.entries.get(entry_id) if isinstance(entry_id, str) else None
            if owner is None or entry_id in seen_entries:
                raise ValueError("Unapproved or duplicate catalog entry")
            public = _public_card(entry, owner, source.domain)
            if entry["path"] in seen_paths:
                raise ValueError("Duplicate projected catalog path")
            seen_entries.add(entry_id)
            seen_paths.add(entry["path"])
            if entry["enabled"]:
                seed_card = cards.get(owner.card_id, (owner.kind, {}))[1]
                updates[owner.card_id] = (owner.kind, {**seed_card, **public})

    for card_id, update in sorted(updates.items()):
        if update is None:
            cards.pop(card_id, None)
        else:
            cards[card_id] = update

    result: dict[str, list[tuple[int, dict]]] = {kind: [] for kind in KINDS}
    positions = {kind: 0 for kind in KINDS}
    urls: set[tuple[str, str]] = set()
    for card_id, (kind, card) in cards.items():
        host, path = _https_url(card.get("url"))
        destination = (host, unquote(path).rstrip("/") or "/")
        if destination in urls:
            raise ValueError("Duplicate catalog destination")
        urls.add(destination)
        fields = editorial.get(card_id, {})
        if not fields.get("hidden", False):
            card.update({key: value for key, value in fields.items() if key not in ("order", "hidden")})
            result[kind].append((fields.get("order", positions[kind]), card))
        positions[kind] += 1
    return {kind: [card for _, card in sorted(rows, key=lambda row: row[0])] for kind, rows in result.items()}
