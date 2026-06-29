import copy
import os
import re
from typing import Any, Dict, Optional

from zoolanding_lambda_common import (
    alias_pk,
    bad_request,
    default_version_prefix,
    get_header_value,
    get_query_value,
    get_request_id,
    get_table,
    join_s3_key,
    load_item,
    load_json_from_s3,
    log,
    normalize_domain,
    normalize_route_path,
    not_found,
    now_iso,
    ok,
    server_error,
    site_pk,
)


CONFIG_TABLE_NAME = os.getenv("CONFIG_TABLE_NAME", "zoolanding-config-registry")
CONFIG_PAYLOADS_BUCKET_NAME = os.getenv("CONFIG_PAYLOADS_BUCKET_NAME", "zoolanding-config-payloads")
CANONICAL_NOT_FOUND_DOMAIN = os.getenv("CANONICAL_NOT_FOUND_DOMAIN", "zoolandingpage.com.mx")
CONTENT_HUB_METADATA_TABLE_NAME = os.getenv("CONTENT_HUB_METADATA_TABLE_NAME", "").strip()
CONTENT_HUB_METADATA_TABLE_NAME_DEV = os.getenv("CONTENT_HUB_METADATA_TABLE_NAME_DEV", "").strip()
CONTENT_HUB_METADATA_TABLE_NAME_TEST = os.getenv("CONTENT_HUB_METADATA_TABLE_NAME_TEST", "").strip()
CONTENT_HUB_METADATA_TABLE_NAME_PROD = os.getenv("CONTENT_HUB_METADATA_TABLE_NAME_PROD", "").strip()
CONTENT_HUB_PACKAGES_BUCKET_NAME = os.getenv("CONTENT_HUB_PACKAGES_BUCKET_NAME", "").strip()
CONTENT_HUB_PACKAGES_BUCKET_NAME_DEV = os.getenv("CONTENT_HUB_PACKAGES_BUCKET_NAME_DEV", "").strip()
CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST = os.getenv("CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST", "").strip()
CONTENT_HUB_PACKAGES_BUCKET_NAME_PROD = os.getenv("CONTENT_HUB_PACKAGES_BUCKET_NAME_PROD", "").strip()
SAFE_CONTENT_HUB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
CONTENT_HUB_SECRET_KEY_RE = re.compile(
    r"(?:access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|credential[_-]?ref|"
    r"secret[_-]?ref|private[_-]?key|server[_-]?policy|table[_-]?name|bucket[_-]?name|"
    r"lambda[_-]?arn|groups[_-]?to[_-]?roles|authorization[_-]?decision|signed[_-]?url|"
    r"tenant[_-]?id|aws[_-]?secret|aws[_-]?access)",
    re.I,
)
CONTENT_HUB_UNSAFE_VALUE_RE = re.compile(
    r"(?:javascript:|data:|X-Amz-Signature|X-Amz-Credential|X-Amz-Security-Token|"
    r"AWSAccessKeyId=|Signature=|Expires=|ssm:/|secretsmanager:/)",
    re.I,
)


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _deep_merge(base: Any, override: Any) -> Any:
    if _is_record(base) and _is_record(override):
        merged = {**base}
        for key, value in override.items():
            merged[key] = _deep_merge(merged.get(key), value) if key in merged else value
        return merged
    return override if override is not None else base


def _resolve_domain(event: Dict[str, Any]) -> str:
    domain = get_query_value(event, "domain")
    if domain:
        return normalize_domain(domain)
    return normalize_domain(
        get_header_value(event, "x-forwarded-host")
        or get_header_value(event, "host")
    )


def _resolve_path(event: Dict[str, Any]) -> str:
    explicit_path = get_query_value(event, "path")
    if explicit_path:
        return normalize_route_path(explicit_path)

    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    raw_path = event.get("rawPath") or http.get("path") or "/"
    return normalize_route_path(str(raw_path))


def _normalize_aliases(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for entry in value:
        alias = normalize_domain(entry)
        if not alias or alias in seen:
            continue
        seen.add(alias)
        normalized.append(alias)

    return normalized


def _normalize_environment(value: Any) -> str:
    environment = str(value or "production").strip().lower()
    if environment in {"prod", "live", "main"}:
        return "production"
    if environment in {"development", "local"}:
        return "dev"
    if environment in {"testing", "stage", "staging"}:
        return "test"
    if environment in {"production", "test", "dev"}:
        return environment
    return "production"


def _requested_environment_override(event: Dict[str, Any]) -> Optional[str]:
    raw_environment = str(get_query_value(event, "environment") or "").strip().lower()
    if not raw_environment:
        return None
    if raw_environment not in {"production", "prod", "live", "main", "test", "testing", "stage", "staging", "dev", "development", "local"}:
        return None
    return _normalize_environment(raw_environment)


def _infer_environment_from_domain(domain: str) -> str:
    normalized = normalize_domain(domain)
    return "test" if normalized.startswith("test.") else "production"


def _normalize_environment_aliases(value: Any) -> Dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}

    normalized: Dict[str, list[str]] = {}
    for environment, aliases in value.items():
        normalized_environment = _normalize_environment(environment)
        normalized_aliases = _normalize_aliases(aliases)
        if normalized_aliases:
            normalized[normalized_environment] = normalized_aliases
    return normalized


def _resolve_site_metadata(domain: str) -> tuple[str, Optional[Dict[str, Any]], Optional[str], str]:
    canonical_domain = normalize_domain(domain)
    if not canonical_domain:
        return "", None, None, "production"

    metadata = load_item(CONFIG_TABLE_NAME, site_pk(canonical_domain))
    if isinstance(metadata, dict):
        return canonical_domain, metadata, None, "production"

    alias_item = load_item(CONFIG_TABLE_NAME, alias_pk(canonical_domain), "SITE")
    if not isinstance(alias_item, dict):
        return canonical_domain, None, None, "production"

    target_domain = normalize_domain(alias_item.get("domain"))
    if not target_domain:
        return canonical_domain, None, None, "production"

    metadata = load_item(CONFIG_TABLE_NAME, site_pk(target_domain))
    if not isinstance(metadata, dict):
        return canonical_domain, None, None, "production"

    environment = _normalize_environment(alias_item.get("environment"))
    if environment == "production":
        aliases = _normalize_aliases(metadata.get("aliases"))
    else:
        aliases = _normalize_environment_aliases(metadata.get("environmentAliases")).get(environment, [])
    if canonical_domain not in aliases:
        return canonical_domain, None, None, "production"

    return target_domain, metadata, canonical_domain, environment


def _published_pointer(metadata: Dict[str, Any], environment: str) -> Optional[Dict[str, Any]]:
    published_environments = metadata.get("publishedEnvironments") if isinstance(metadata.get("publishedEnvironments"), dict) else {}
    if environment != "production":
        pointer = published_environments.get(environment)
        return pointer if isinstance(pointer, dict) else None

    legacy_pointer = metadata.get("published") if isinstance(metadata.get("published"), dict) else None
    if legacy_pointer:
        return legacy_pointer
    pointer = published_environments.get("production")
    return pointer if isinstance(pointer, dict) else None


def _public_content_hubs(metadata: Dict[str, Any]) -> list[Dict[str, Any]]:
    raw_hubs = metadata.get("contentHubs")
    if not isinstance(raw_hubs, list):
        return []

    public_hubs: list[Dict[str, Any]] = []
    for raw_hub in raw_hubs:
        if not isinstance(raw_hub, dict):
            continue
        hub_id = str(raw_hub.get("hubId") or "").strip()
        if not hub_id:
            continue
        public_hub: Dict[str, Any] = {
            "hubId": hub_id,
            "name": str(raw_hub.get("name") or hub_id).strip() or hub_id,
            "defaultLanguage": str(raw_hub.get("defaultLanguage") or "es").strip() or "es",
            "canonicalDraftDomain": normalize_domain(raw_hub.get("canonicalDraftDomain") or metadata.get("domain") or ""),
        }
        public_hubs.append(public_hub)
    return public_hubs


def _content_hub_table_name(environment: Optional[str] = None) -> str:
    normalized_environment = _normalize_environment(environment) if environment else ""
    env_specific = {
        "dev": os.getenv("CONTENT_HUB_METADATA_TABLE_NAME_DEV", CONTENT_HUB_METADATA_TABLE_NAME_DEV).strip(),
        "test": os.getenv("CONTENT_HUB_METADATA_TABLE_NAME_TEST", CONTENT_HUB_METADATA_TABLE_NAME_TEST).strip(),
        "production": os.getenv("CONTENT_HUB_METADATA_TABLE_NAME_PROD", CONTENT_HUB_METADATA_TABLE_NAME_PROD).strip(),
    }.get(normalized_environment, "")
    return env_specific or os.getenv("CONTENT_HUB_METADATA_TABLE_NAME", CONTENT_HUB_METADATA_TABLE_NAME).strip()


def _content_hub_packages_bucket_name(environment: Optional[str] = None) -> str:
    normalized_environment = _normalize_environment(environment) if environment else ""
    env_specific = {
        "dev": os.getenv("CONTENT_HUB_PACKAGES_BUCKET_NAME_DEV", CONTENT_HUB_PACKAGES_BUCKET_NAME_DEV).strip(),
        "test": os.getenv("CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST", CONTENT_HUB_PACKAGES_BUCKET_NAME_TEST).strip(),
        "production": os.getenv("CONTENT_HUB_PACKAGES_BUCKET_NAME_PROD", CONTENT_HUB_PACKAGES_BUCKET_NAME_PROD).strip(),
    }.get(normalized_environment, "")
    return env_specific or os.getenv("CONTENT_HUB_PACKAGES_BUCKET_NAME", CONTENT_HUB_PACKAGES_BUCKET_NAME).strip()


def _content_hub_environment_segment(environment: str) -> str:
    return "prod" if _normalize_environment(environment) == "production" else _normalize_environment(environment)


def _safe_content_hub_id(value: Any) -> str:
    text = str(value or "").strip()
    return text if SAFE_CONTENT_HUB_ID_RE.fullmatch(text) else ""


def _safe_content_hub_path(value: Any) -> str:
    raw_path = str(value or "").strip()
    if not raw_path:
        return ""
    path = normalize_route_path(raw_path)
    if not path.startswith("/") or path.startswith("//") or "\\" in path or re.search(r"[\s\x00-\x1f\x7f]", path):
        return ""
    return path


def _safe_content_hub_bundle_key(
    value: Any,
    *,
    environment: str,
    hub_id: str,
    render_domain: str,
    locale: str,
    article_id: str,
) -> str:
    key = str(value or "").strip()
    if not key or "\\" in key or re.search(r"[\s\x00-\x1f\x7f]", key):
        return ""
    parts = [part for part in key.split("/") if part]
    if len(parts) != 9 or ".." in parts:
        return ""
    expected = [
        "content-hubs",
        _content_hub_environment_segment(environment),
        hub_id,
        "published",
        render_domain,
        locale,
        article_id,
    ]
    if parts[:7] != expected or not _safe_content_hub_id(parts[7]) or parts[8] != "bundle.json":
        return ""
    return "/".join(parts)


def _safe_content_hub_text(value: Any, max_length: int) -> str:
    text = str(value or "").strip()
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text):
        return ""
    return text[:max_length]


def _public_content_hub_payload(value: Any) -> Any:
    if isinstance(value, dict):
        output: Dict[str, Any] = {}
        for key, entry in value.items():
            if CONTENT_HUB_SECRET_KEY_RE.search(str(key)):
                continue
            sanitized = _public_content_hub_payload(entry)
            if sanitized is not None:
                output[key] = sanitized
        return output
    if isinstance(value, list):
        output = []
        for entry in value:
            sanitized = _public_content_hub_payload(entry)
            if sanitized is not None:
                output.append(sanitized)
        return output
    if isinstance(value, str) and CONTENT_HUB_UNSAFE_VALUE_RE.search(value):
        return None
    return value


def _safe_content_hub_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    return text if text and re.fullmatch(r"\d{4}-\d{2}-\d{2}T[0-9:.+-]+Z?", text) else ""


def _content_hub_locale(hub: Dict[str, Any], lang: str) -> str:
    requested = _safe_content_hub_id(lang.lower())
    locales = hub.get("locales")
    allowed = {str(entry).strip().lower() for entry in locales} if isinstance(locales, list) else set()
    if requested and (not allowed or requested in allowed):
        return requested
    return _safe_content_hub_id(str(hub.get("defaultLocale") or hub.get("defaultLanguage") or "es").lower()) or "es"


def _content_hub_taxonomy_slug(value: Any) -> str:
    if isinstance(value, str):
        return _safe_content_hub_id(value)
    if isinstance(value, dict):
        for field in ("slug", "taxonomyId", "label"):
            safe = _safe_content_hub_id(value.get(field))
            if safe:
                return safe
    return ""


def _content_hub_tags(value: Any) -> list[str]:
    raw_items = [part.strip() for part in value.split(",")] if isinstance(value, str) else value
    if not isinstance(raw_items, list):
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for entry in raw_items:
        tag = _content_hub_taxonomy_slug(entry)
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags[:20]


def _content_hub_article_summary(item: Dict[str, Any], hub: Dict[str, Any], locale: str) -> Optional[Dict[str, Any]]:
    if str(item.get("status") or "").strip() != "published":
        return None
    if str(item.get("visibility") or "").strip() != "public":
        return None

    item_locale = _safe_content_hub_id(str(item.get("primaryLocale") or locale).lower())
    if item_locale and item_locale != locale:
        return None

    article_id = _safe_content_hub_id(item.get("articleId"))
    title = _safe_content_hub_text(item.get("title"), 160)
    path = _safe_content_hub_path(item.get("path"))
    published_at = _safe_content_hub_timestamp(item.get("publishedAt") or item.get("updatedAt"))
    if not article_id or not title or not path or not published_at:
        return None

    category_slug = _content_hub_taxonomy_slug(item.get("category"))
    tags = _content_hub_tags(item.get("tags"))
    robots = str(item.get("robots") or "index,follow").strip()
    if robots not in {"index,follow", "noindex,follow", "noindex,nofollow"}:
        robots = "index,follow"

    summary: Dict[str, Any] = {
        "articleId": article_id,
        "locale": item_locale or locale,
        "status": "published",
        "title": title,
        "path": path,
        "publishedAt": published_at,
        "robots": robots,
    }
    description = _safe_content_hub_text(item.get("summary") or item.get("seoDescription"), 320)
    updated_at = _safe_content_hub_timestamp(item.get("updatedAt"))
    author_label = _safe_content_hub_text(item.get("authorLabel"), 120)
    canonical_path = _safe_content_hub_path(item.get("canonicalPath") or item.get("canonicalUrl"))
    if description:
        summary["summary"] = description
    if category_slug:
        summary["categorySlug"] = category_slug
    if tags:
        summary["tags"] = tags
    if updated_at:
        summary["updatedAt"] = updated_at
    if author_label:
        summary["authorLabel"] = author_label
    if canonical_path:
        summary["canonicalPath"] = canonical_path
    elif path:
        summary["canonicalPath"] = path
    return summary


def _content_hub_taxonomy_summary(item: Dict[str, Any], default_kind: str, locale: str) -> Optional[Dict[str, Any]]:
    kind = str(item.get("kind") or default_kind).strip()
    if kind not in {"category", "tag"}:
        return None
    if item.get("visible") is False:
        return None
    item_locale = _safe_content_hub_id(str(item.get("locale") or locale).lower())
    if item_locale and item_locale != locale:
        return None
    taxonomy_id = _safe_content_hub_id(item.get("taxonomyId") or item.get("slug") or item.get("label"))
    slug = _safe_content_hub_id(item.get("slug") or taxonomy_id)
    label = _safe_content_hub_text(item.get("label") or slug, 120)
    if not taxonomy_id or not slug or not label:
        return None
    summary: Dict[str, Any] = {
        "taxonomyId": taxonomy_id,
        "kind": kind,
        "slug": slug,
        "label": label,
        "locale": item_locale or locale,
        "visible": True,
    }
    if kind == "category":
        summary["path"] = _safe_content_hub_path(item.get("path") or f"/blog/{slug}")
    return summary


def _query_content_hub_metadata(hub_id: str, sk_prefix: str, environment: str) -> list[Dict[str, Any]]:
    table_name = _content_hub_table_name(environment)
    if not table_name:
        return []
    try:
        response = get_table(table_name).query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :sk)",
            ExpressionAttributeValues={":pk": f"HUB#{hub_id}", ":sk": sk_prefix},
            Limit=200,
        )
    except Exception as exc:
        log("WARNING", "Content hub public index query failed", hubId=hub_id, skPrefix=sk_prefix, error=str(exc))
        return []
    items = response.get("Items")
    return items if isinstance(items, list) else []


def _load_content_hub_json_bundle(
    key: str,
    environment: str,
    hub_id: str,
    render_domain: str,
    locale: str,
    article_id: str,
) -> Optional[Dict[str, Any]]:
    bucket_name = _content_hub_packages_bucket_name(environment)
    safe_key = _safe_content_hub_bundle_key(
        key,
        environment=environment,
        hub_id=hub_id,
        render_domain=render_domain,
        locale=locale,
        article_id=article_id,
    )
    if not bucket_name or not safe_key:
        return None
    try:
        payload = load_json_from_s3(bucket_name, safe_key)
    except Exception as exc:
        log("WARNING", "Content hub public bundle read failed", error=str(exc))
        return None
    return payload if isinstance(payload, dict) else None


def _public_content_hub_bundle(bundle: Optional[Dict[str, Any]], article: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(bundle, dict):
        return None
    if _safe_content_hub_id(bundle.get("articleId")) != _safe_content_hub_id(article.get("articleId")):
        return None
    bundle_path = _safe_content_hub_path(bundle.get("path"))
    article_path = _safe_content_hub_path(article.get("path"))
    if bundle_path and article_path and bundle_path != article_path:
        return None
    if str(bundle.get("status") or "published").strip() != "published":
        return None

    public_bundle = _public_content_hub_payload(bundle)
    if not isinstance(public_bundle, dict):
        return None
    output: Dict[str, Any] = {}
    for key in ("components", "structuredData"):
        if isinstance(public_bundle.get(key), list):
            output[key] = public_bundle[key]
    for key in ("variables", "i18n", "seo", "analytics"):
        if isinstance(public_bundle.get(key), dict):
            output[key] = public_bundle[key]
    return output or None


def _content_hub_bundle_for_path(
    site_config: Optional[Dict[str, Any]],
    path: str,
    lang: str,
    environment: str,
) -> Optional[Dict[str, Any]]:
    if not isinstance(site_config, dict) or not _content_hub_table_name(environment) or not _content_hub_packages_bucket_name(environment):
        return None
    runtime = site_config.get("runtime")
    hubs = runtime.get("contentHubs") if isinstance(runtime, dict) else None
    if not isinstance(hubs, list):
        return None

    normalized_path = normalize_route_path(path)
    render_domain = normalize_domain(site_config.get("domain"))
    if not render_domain:
        return None
    for hub in hubs:
        if not isinstance(hub, dict):
            continue
        hub_id = _safe_content_hub_id(hub.get("hubId"))
        if not hub_id:
            continue
        locale = _content_hub_locale(hub, lang)
        for item in _query_content_hub_metadata(hub_id, "ARTICLE#", environment):
            article = _content_hub_article_summary(item, hub, locale)
            if not article or _safe_content_hub_path(article.get("path")) != normalized_path:
                continue
            article_id = _safe_content_hub_id(article.get("articleId"))
            bundle = _load_content_hub_json_bundle(
                str(item.get("publishedBundleKey") or ""),
                environment,
                hub_id,
                render_domain,
                locale,
                article_id,
            )
            return _public_content_hub_bundle(bundle, article)
    return None


def _dedupe_content_hub_items(items: list[Dict[str, Any]], key_fields: tuple[str, ...]) -> list[Dict[str, Any]]:
    output: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = "|".join(str(item.get(field) or "") for field in key_fields)
        if not key.strip("|") or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _content_hub_taxonomy_from_articles(articles: list[Dict[str, Any]], locale: str) -> list[Dict[str, Any]]:
    taxonomy: list[Dict[str, Any]] = []
    for article in articles:
        category = _safe_content_hub_id(article.get("categorySlug"))
        if category:
            taxonomy.append({
                "taxonomyId": category,
                "kind": "category",
                "slug": category,
                "label": category.replace("-", " ").title(),
                "locale": locale,
                "visible": True,
                "path": f"/blog/{category}",
            })
        for tag in article.get("tags") or []:
            safe_tag = _safe_content_hub_id(tag)
            if safe_tag:
                taxonomy.append({
                    "taxonomyId": safe_tag,
                    "kind": "tag",
                    "slug": safe_tag,
                    "label": safe_tag.replace("-", " ").title(),
                    "locale": locale,
                    "visible": True,
                })
    return taxonomy


def _merge_content_hub_runtime_indexes(site_config: Optional[Dict[str, Any]], lang: str, environment: str) -> Optional[Dict[str, Any]]:
    if not isinstance(site_config, dict) or not _content_hub_table_name(environment):
        return site_config
    runtime = site_config.get("runtime")
    hubs = runtime.get("contentHubs") if isinstance(runtime, dict) else None
    if not isinstance(hubs, list):
        return site_config

    enriched = copy.deepcopy(site_config)
    enriched_hubs = enriched["runtime"]["contentHubs"]
    for hub in enriched_hubs:
        if not isinstance(hub, dict):
            continue
        hub_id = _safe_content_hub_id(hub.get("hubId"))
        if not hub_id:
            continue
        locale = _content_hub_locale(hub, lang)
        dynamic_articles = [
            article
            for item in _query_content_hub_metadata(hub_id, "ARTICLE#", environment)
            for article in [_content_hub_article_summary(item, hub, locale)]
            if article
        ]
        existing_articles = hub.get("publicArticles") if isinstance(hub.get("publicArticles"), list) else []
        merged_articles = _dedupe_content_hub_items(
            sorted(dynamic_articles, key=lambda item: str(item.get("publishedAt") or ""), reverse=True)
            + [item for item in existing_articles if isinstance(item, dict)],
            ("articleId",),
        )
        if merged_articles:
            hub["publicArticles"] = merged_articles

        dynamic_taxonomy = [
            taxonomy
            for item in _query_content_hub_metadata(hub_id, "TAXONOMY#", environment)
            for taxonomy in [_content_hub_taxonomy_summary(item, "", locale)]
            if taxonomy
        ]
        existing_taxonomy = hub.get("publicTaxonomy") if isinstance(hub.get("publicTaxonomy"), list) else []
        merged_taxonomy = _dedupe_content_hub_items(
            dynamic_taxonomy
            + _content_hub_taxonomy_from_articles(merged_articles, locale)
            + [item for item in existing_taxonomy if isinstance(item, dict)],
            ("kind", "slug"),
        )
        if merged_taxonomy:
            hub["publicTaxonomy"] = merged_taxonomy
    return enriched


def _content_hub_public_variables(site_config: Optional[Dict[str, Any]], path: str) -> Optional[Dict[str, Any]]:
    runtime = site_config.get("runtime") if isinstance(site_config, dict) else None
    hubs = runtime.get("contentHubs") if isinstance(runtime, dict) else None
    if not isinstance(hubs, list) or not hubs:
        return None
    valid_hubs = [entry for entry in hubs if isinstance(entry, dict)]
    if not valid_hubs:
        return None
    articles = [
        item
        for hub in valid_hubs
        for item in (hub.get("publicArticles", []) if isinstance(hub.get("publicArticles"), list) else [])
        if isinstance(item, dict)
    ]
    taxonomy = [
        item
        for hub in valid_hubs
        for item in (hub.get("publicTaxonomy", []) if isinstance(hub.get("publicTaxonomy"), list) else [])
        if isinstance(item, dict)
    ]
    categories = [item for item in taxonomy if item.get("kind") == "category"]
    tags = [item for item in taxonomy if item.get("kind") == "tag"]
    normalized_path = normalize_route_path(path)
    current_article = None
    current_hub = valid_hubs[0]
    for hub_entry in valid_hubs:
        hub_articles = hub_entry.get("publicArticles", []) if isinstance(hub_entry.get("publicArticles"), list) else []
        current_article = next((
            item for item in hub_articles
            if isinstance(item, dict) and _safe_content_hub_path(item.get("path")) == normalized_path
        ), None)
        if current_article:
            current_hub = hub_entry
            break
    return {
        "hubId": current_hub.get("hubId"),
        "routeBasePath": current_hub.get("routeBasePath") or "/blog",
        "publicArticles": {"items": articles},
        "publicTaxonomy": {"items": taxonomy},
        "categories": {"items": categories},
        "tags": {"items": tags},
        "articleCount": len(articles),
        "currentArticle": current_article or {},
    }


def _route_pattern_matches(pattern: Any, path: str) -> bool:
    route_path = normalize_route_path(pattern or "")
    normalized_path = normalize_route_path(path)
    if not route_path or ":" not in route_path:
        return route_path == normalized_path
    route_segments = [segment for segment in route_path.split("/") if segment]
    path_segments = [segment for segment in normalized_path.split("/") if segment]
    return len(route_segments) == len(path_segments) and all(
        route_segment.startswith(":") or route_segment == path_segment
        for route_segment, path_segment in zip(route_segments, path_segments)
    )


def _is_content_hub_article_path(site_config: Optional[Dict[str, Any]], path: str) -> bool:
    runtime = site_config.get("runtime") if isinstance(site_config, dict) else None
    hubs = runtime.get("contentHubs") if isinstance(runtime, dict) else None
    if not isinstance(hubs, list):
        return False
    for hub in hubs:
        if not isinstance(hub, dict):
            continue
        pattern = hub.get("articlePathPattern")
        if pattern and _route_pattern_matches(pattern, path):
            return True
    return False


def _merge_content_hub_variables(
    variables_payload: Optional[Dict[str, Any]],
    site_config: Optional[Dict[str, Any]],
    path: str,
) -> Optional[Dict[str, Any]]:
    content_hub = _content_hub_public_variables(site_config, path)
    if not content_hub:
        return variables_payload
    payload = copy.deepcopy(variables_payload) if isinstance(variables_payload, dict) else {"version": 1, "variables": {}}
    variables = payload.get("variables")
    if not isinstance(variables, dict):
        variables = {}
    variables["contentHub"] = _deep_merge(variables.get("contentHub"), content_hub)
    payload["variables"] = variables
    return payload


def _merge_content_hub_bundle_variables(
    variables_payload: Optional[Dict[str, Any]],
    article_bundle: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    bundle_variables = article_bundle.get("variables") if isinstance(article_bundle, dict) else None
    if not isinstance(bundle_variables, dict):
        return variables_payload
    payload = copy.deepcopy(variables_payload) if isinstance(variables_payload, dict) else {"version": 1, "variables": {}}
    variables = payload.get("variables") if isinstance(payload.get("variables"), dict) else {}
    payload["variables"] = _deep_merge(variables, bundle_variables)
    return payload


def _content_hub_current_article(variables_payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    variables = variables_payload.get("variables") if isinstance(variables_payload, dict) else None
    content_hub = variables.get("contentHub") if isinstance(variables, dict) else None
    article = content_hub.get("currentArticle") if isinstance(content_hub, dict) else None
    return article if isinstance(article, dict) and article.get("articleId") else None


def _site_seo_config(site_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    site = site_config.get("site") if isinstance(site_config, dict) else None
    seo = site.get("seo") if isinstance(site, dict) else None
    return seo if isinstance(seo, dict) else {}


def _article_canonical_url(site_config: Optional[Dict[str, Any]], article: Dict[str, Any]) -> Optional[str]:
    path = _safe_content_hub_path(article.get("canonicalPath")) or _safe_content_hub_path(article.get("path"))
    if not path:
        return None
    seo = _site_seo_config(site_config)
    origin = str(seo.get("canonicalOrigin") or "").strip().rstrip("/")
    if not origin.startswith("https://"):
        domain = str((site_config or {}).get("domain") or "").strip()
        origin = f"https://{domain}" if domain else ""
    return f"{origin}{path}" if origin else path


def _merge_content_hub_page_config_seo(
    page_config: Optional[Dict[str, Any]],
    site_config: Optional[Dict[str, Any]],
    variables_payload: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    article = _content_hub_current_article(variables_payload)
    if not isinstance(page_config, dict) or not article:
        return page_config

    title = str(article.get("title") or "").strip()
    summary = str(article.get("summary") or "").strip()
    robots = str(article.get("robots") or "").strip()
    canonical = _article_canonical_url(site_config, article)
    if not any((title, summary, robots, canonical)):
        return page_config

    enriched = copy.deepcopy(page_config)
    seo = enriched.get("seo") if isinstance(enriched.get("seo"), dict) else {}
    site_seo = _site_seo_config(site_config)
    site_name = str(site_seo.get("siteName") or (site_config or {}).get("domain") or "").strip()
    if title:
        seo["title"] = f"{title} | {site_name}" if site_name and site_name not in title else title
    if summary:
        seo["description"] = summary
    if canonical:
        seo["canonical"] = canonical
    if robots:
        seo["robots"] = {"default": robots}
    enriched["seo"] = seo
    return enriched


def _absolute_content_hub_canonical(site_config: Optional[Dict[str, Any]], canonical: Any) -> Optional[str]:
    path = _safe_content_hub_path(canonical)
    if not path:
        return None
    seo = _site_seo_config(site_config)
    origin = str(seo.get("canonicalOrigin") or "").strip().rstrip("/")
    if not origin.startswith("https://"):
        domain = str((site_config or {}).get("domain") or "").strip()
        origin = f"https://{domain}" if domain else ""
    return f"{origin}{path}" if origin else path


def _merge_content_hub_bundle_page_config_seo(
    page_config: Optional[Dict[str, Any]],
    site_config: Optional[Dict[str, Any]],
    article_bundle: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    bundle_seo = article_bundle.get("seo") if isinstance(article_bundle, dict) else None
    if not isinstance(page_config, dict) or not isinstance(bundle_seo, dict):
        return page_config

    enriched = copy.deepcopy(page_config)
    seo = enriched.get("seo") if isinstance(enriched.get("seo"), dict) else {}
    site_seo = _site_seo_config(site_config)
    site_name = str(site_seo.get("siteName") or (site_config or {}).get("domain") or "").strip()
    title = _safe_content_hub_text(bundle_seo.get("title"), 160)
    description = _safe_content_hub_text(bundle_seo.get("description"), 320)
    canonical = _absolute_content_hub_canonical(site_config, bundle_seo.get("canonical"))
    robots = _safe_content_hub_text(bundle_seo.get("robots"), 160)

    if title:
        seo["title"] = f"{title} | {site_name}" if site_name and site_name not in title else title
    if description:
        seo["description"] = description
    if canonical:
        seo["canonical"] = canonical
    if robots:
        seo["robots"] = {"default": robots}
    enriched["seo"] = seo
    return enriched


def _public_site_config(site_config: Dict[str, Any]) -> Dict[str, Any]:
    public_config = copy.deepcopy(site_config)
    if isinstance(public_config.get("contentHubs"), list):
        public_hubs = _public_content_hubs(public_config)
        if public_hubs:
            public_config["contentHubs"] = public_hubs
        else:
            public_config.pop("contentHubs", None)
    return public_config


def _match_route(metadata: Dict[str, Any], path: str) -> Optional[Dict[str, Any]]:
    normalized_path = normalize_route_path(path)
    parameterized_match: Optional[Dict[str, Any]] = None

    for route in metadata.get("routes", []):
        if not isinstance(route, dict):
            continue
        route_path = normalize_route_path(route.get("path", "/"))
        if route_path == normalized_path:
            return route

        if parameterized_match is not None or ":" not in route_path:
            continue

        route_segments = [segment for segment in route_path.split("/") if segment]
        path_segments = [segment for segment in normalized_path.split("/") if segment]
        if len(route_segments) != len(path_segments):
            continue
        if all(route_segment.startswith(":") or route_segment == path_segment for route_segment, path_segment in zip(route_segments, path_segments)):
            parameterized_match = route

    if parameterized_match is not None:
        return parameterized_match
    return None


def _resolve_route(metadata: Dict[str, Any], site_config: Optional[Dict[str, Any]], path: str) -> Optional[Dict[str, Any]]:
    return _match_route(metadata, path) or (_match_route(site_config, path) if isinstance(site_config, dict) else None)


def _resolve_default_page_id(metadata: Dict[str, Any], site_config: Optional[Dict[str, Any]]) -> str:
    configured = site_config.get("defaultPageId") if isinstance(site_config, dict) else None
    return str(configured or metadata.get("defaultPageId") or "default").strip() or "default"


def _resolve_not_found_page_id(metadata: Dict[str, Any], site_config: Optional[Dict[str, Any]]) -> str:
    for source in (site_config, metadata):
        if not isinstance(source, dict):
            continue
        configured = str(source.get("notFoundPageId") or "").strip()
        if configured:
            return configured

    route = _resolve_route(metadata, site_config, "/404")
    return str((route or {}).get("pageId") or "").strip()


def _load_payload(bucket: str, prefix: str, relative_path: str) -> Optional[Dict[str, Any]]:
    key = join_s3_key(prefix, relative_path)
    return load_json_from_s3(bucket, key)


def _load_runtime_payloads(domain: str, prefix: str, page_id: str, lang: str, site_config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    page_config = _load_payload(CONFIG_PAYLOADS_BUCKET_NAME, prefix, f"{domain}/{page_id}/page-config.json")
    shared_components = _load_payload(CONFIG_PAYLOADS_BUCKET_NAME, prefix, f"{domain}/components.json")
    page_components = _load_payload(CONFIG_PAYLOADS_BUCKET_NAME, prefix, f"{domain}/{page_id}/components.json")
    shared_variables = _load_payload(CONFIG_PAYLOADS_BUCKET_NAME, prefix, f"{domain}/variables.json")
    page_variables = _load_payload(CONFIG_PAYLOADS_BUCKET_NAME, prefix, f"{domain}/{page_id}/variables.json")
    shared_angora_combos = _load_payload(CONFIG_PAYLOADS_BUCKET_NAME, prefix, f"{domain}/angora-combos.json")
    page_angora_combos = _load_payload(CONFIG_PAYLOADS_BUCKET_NAME, prefix, f"{domain}/{page_id}/angora-combos.json")
    shared_i18n = _load_payload(CONFIG_PAYLOADS_BUCKET_NAME, prefix, f"{domain}/i18n/{lang}.json")
    page_i18n = _load_payload(CONFIG_PAYLOADS_BUCKET_NAME, prefix, f"{domain}/{page_id}/i18n/{lang}.json")

    if not site_config or not page_config or not page_components:
        return None

    return {
        "siteConfig": site_config,
        "pageConfig": page_config,
        "sharedComponents": shared_components,
        "pageComponents": page_components,
        "sharedVariables": shared_variables,
        "pageVariables": page_variables,
        "sharedAngoraCombos": shared_angora_combos,
        "pageAngoraCombos": page_angora_combos,
        "sharedI18n": shared_i18n,
        "pageI18n": page_i18n,
    }


def _merge_components(
    domain: str,
    page_id: str,
    shared_payload: Optional[Dict[str, Any]],
    page_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}

    for payload in (shared_payload, page_payload):
        if not isinstance(payload, dict):
            continue
        for component in payload.get("components", []):
            if not isinstance(component, dict):
                continue
            component_id = str(component.get("id") or "").strip()
            if not component_id:
                continue
            merged[component_id] = component

    return {
        "version": page_payload.get("version") if isinstance(page_payload, dict) else 1,
        "domain": domain,
        "pageId": page_id,
        "components": list(merged.values()),
    }


def _merge_content_hub_bundle_components(
    components_payload: Dict[str, Any],
    article_bundle: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    bundle_components = article_bundle.get("components") if isinstance(article_bundle, dict) else None
    if not isinstance(bundle_components, list):
        return components_payload

    merged: dict[str, dict[str, Any]] = {}
    for component in components_payload.get("components", []):
        if not isinstance(component, dict):
            continue
        component_id = str(component.get("id") or "").strip()
        if component_id:
            merged[component_id] = component
    for component in bundle_components:
        if not isinstance(component, dict):
            continue
        component_id = str(component.get("id") or "").strip()
        component_type = str(component.get("type") or "").strip()
        if component_id and component_type:
            merged[component_id] = component

    output = copy.deepcopy(components_payload)
    output["components"] = list(merged.values())
    return output


def _merge_variables(
    domain: str,
    page_id: str,
    shared_payload: Optional[Dict[str, Any]],
    page_payload: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(shared_payload, dict) and not isinstance(page_payload, dict):
        return None

    shared_variables = shared_payload.get("variables") if isinstance(shared_payload, dict) and isinstance(shared_payload.get("variables"), dict) else {}
    page_variables = page_payload.get("variables") if isinstance(page_payload, dict) and isinstance(page_payload.get("variables"), dict) else {}
    shared_computed = shared_payload.get("computed") if isinstance(shared_payload, dict) and isinstance(shared_payload.get("computed"), dict) else {}
    page_computed = page_payload.get("computed") if isinstance(page_payload, dict) and isinstance(page_payload.get("computed"), dict) else {}

    return {
        "version": (page_payload or shared_payload or {}).get("version", 1),
        "domain": domain,
        "pageId": page_id,
        "variables": _deep_merge(shared_variables, page_variables),
        "computed": _deep_merge(shared_computed, page_computed),
    }


def _merge_angora_combos(
    domain: str,
    page_id: str,
    shared_payload: Optional[Dict[str, Any]],
    page_payload: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(shared_payload, dict) and not isinstance(page_payload, dict):
        return None

    shared_combos = shared_payload.get("combos") if isinstance(shared_payload, dict) and isinstance(shared_payload.get("combos"), dict) else {}
    page_combos = page_payload.get("combos") if isinstance(page_payload, dict) and isinstance(page_payload.get("combos"), dict) else {}

    return {
        "version": (page_payload or shared_payload or {}).get("version", 1),
        "domain": domain,
        "pageId": page_id,
        "combos": {**shared_combos, **page_combos},
    }


def _merge_i18n(
    domain: str,
    page_id: str,
    lang: str,
    shared_payload: Optional[Dict[str, Any]],
    page_payload: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(shared_payload, dict) and not isinstance(page_payload, dict):
        return None

    shared_dictionary = shared_payload.get("dictionary") if isinstance(shared_payload, dict) and isinstance(shared_payload.get("dictionary"), dict) else {}
    page_dictionary = page_payload.get("dictionary") if isinstance(page_payload, dict) and isinstance(page_payload.get("dictionary"), dict) else {}

    return {
        "version": (page_payload or shared_payload or {}).get("version", 1),
        "domain": domain,
        "pageId": page_id,
        "lang": str((page_payload or shared_payload or {}).get("lang") or lang),
        "dictionary": _deep_merge(shared_dictionary, page_dictionary),
    }


def _merge_content_hub_bundle_i18n(
    i18n_payload: Optional[Dict[str, Any]],
    article_bundle: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    bundle_i18n = article_bundle.get("i18n") if isinstance(article_bundle, dict) else None
    if not isinstance(bundle_i18n, dict):
        return i18n_payload
    bundle_dictionary = bundle_i18n.get("dictionary") if isinstance(bundle_i18n.get("dictionary"), dict) else bundle_i18n
    if not isinstance(bundle_dictionary, dict):
        return i18n_payload

    payload = copy.deepcopy(i18n_payload) if isinstance(i18n_payload, dict) else {"version": 1, "dictionary": {}}
    dictionary = payload.get("dictionary") if isinstance(payload.get("dictionary"), dict) else {}
    payload["dictionary"] = _deep_merge(dictionary, bundle_dictionary)
    return payload


def _fallback_bundle(domain: str, page_id: str, metadata: Dict[str, Any], lifecycle: Dict[str, Any]) -> Dict[str, Any]:
    message = str(lifecycle.get("message") or "This site is currently unavailable. Please contact the administrator.")
    status = str(lifecycle.get("status") or "maintenance")

    site_config = {
        "version": 1,
        "domain": domain,
        "aliases": metadata.get("aliases", []),
        "defaultPageId": page_id,
        "routes": metadata.get("routes", [{"path": "/", "pageId": page_id, "label": "Unavailable"}]),
        "lifecycle": lifecycle,
        "site": {
            "appIdentity": {
                "identifier": "zoolandingpage-fallback",
                "name": "Zoolandingpage",
                "version": "2.0.0",
                "description": "Lifecycle fallback experience",
            },
            "theme": {
                "defaultMode": "light",
                "palettes": {
                    "light": {
                        "bgColor": "#f7f1e9",
                        "textColor": "#1d2429",
                        "titleColor": "#152026",
                        "linkColor": "#8a3d14",
                        "accentColor": "#c45d1c",
                        "secondaryBgColor": "#efe3d3",
                        "secondaryTextColor": "#384149",
                        "secondaryTitleColor": "#152026",
                        "secondaryLinkColor": "#8a3d14",
                        "secondaryAccentColor": "#c45d1c",
                    },
                    "dark": {
                        "bgColor": "#172026",
                        "textColor": "#f6efe5",
                        "titleColor": "#fff9f3",
                        "linkColor": "#f9a46b",
                        "accentColor": "#ff7e36",
                        "secondaryBgColor": "#22313a",
                        "secondaryTextColor": "#dbcdbd",
                        "secondaryTitleColor": "#fff9f3",
                        "secondaryLinkColor": "#f9a46b",
                        "secondaryAccentColor": "#ff7e36",
                    },
                },
            },
            "i18n": {
                "defaultLanguage": "en",
                "supportedLanguages": ["en"],
            },
            "seo": {
                "siteName": "Zoolandingpage",
                "title": "Site unavailable",
                "description": message,
            },
        },
        "defaults": {
            "brand": {
                "displayName": "Zoolandingpage",
                "tagline": "Managed landing page service",
            },
        },
    }

    page_config = {
        "version": 1,
        "domain": domain,
        "pageId": page_id,
        "rootIds": ["lifecycleNotice"],
        "seo": {
            "title": f"Site {status}",
            "description": message,
        },
    }

    components = {
        "version": 1,
        "domain": domain,
        "pageId": page_id,
        "components": [
            {
                "id": "lifecycleNotice",
                "type": "container",
                "config": {
                    "tag": "section",
                    "classes": "ank-minHeight-100vh ank-display-flex ank-justifyContent-center ank-alignItems-center ank-padding-2rem ank-bgColor-bgColor",
                    "components": ["lifecycleCard"],
                },
            },
            {
                "id": "lifecycleCard",
                "type": "container",
                "config": {
                    "tag": "div",
                    "classes": "ank-maxWidth-720px ank-width-100p ank-padding-2rem ank-borderRadius-24px ank-bgColor-secondaryBgColor ank-display-flex ank-flexDirection-column ank-gap-1rem ank-boxShadow-0_18px_48px_rgba(0,0,0,0.12)",
                    "components": ["lifecycleTitle", "lifecycleMessage"],
                },
            },
            {
                "id": "lifecycleTitle",
                "type": "text",
                "config": {
                    "tag": "h1",
                    "classes": "ank-fontSize-2rem ank-fontWeight-700 ank-color-titleColor",
                    "text": "Site temporarily unavailable",
                },
            },
            {
                "id": "lifecycleMessage",
                "type": "text",
                "config": {
                    "tag": "p",
                    "classes": "ank-fontSize-1rem ank-lineHeight-1_6 ank-color-textColor",
                    "text": message,
                },
            },
        ],
    }

    return {
        "version": 1,
        "domain": domain,
        "pageId": page_id,
        "sourceStage": "fallback",
        "generatedAt": now_iso(),
        "lifecycle": lifecycle,
        "siteConfig": site_config,
        "pageConfig": page_config,
        "components": components,
        "metadata": {
            "status": status,
            "fallbackMode": lifecycle.get("fallbackMode", "system"),
        },
    }


def _published_bundle(
    *,
    request_id: str,
    requested_domain: str,
    domain: str,
    resolved_alias: Optional[str],
    environment: str,
    version_id: str,
    prefix: str,
    path: str,
    lang: str,
    lifecycle: Dict[str, Any],
    site_metadata: Dict[str, Any],
    route: Optional[Dict[str, Any]],
    page_id: str,
    payloads: Dict[str, Any],
    not_found_status: bool = False,
    fallback_from_domain: Optional[str] = None,
    article_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if article_bundle is None and not not_found_status:
        article_bundle = _content_hub_bundle_for_path(payloads["siteConfig"], path, lang, environment)
    variables_payload = _merge_content_hub_variables(
        _merge_variables(domain, page_id, payloads["sharedVariables"], payloads["pageVariables"]),
        payloads["siteConfig"],
        path,
    )
    variables_payload = _merge_content_hub_bundle_variables(variables_payload, article_bundle)
    page_config = _merge_content_hub_page_config_seo(
        payloads["pageConfig"],
        payloads["siteConfig"],
        variables_payload,
    )
    page_config = _merge_content_hub_bundle_page_config_seo(
        page_config,
        payloads["siteConfig"],
        article_bundle,
    )
    components_payload = _merge_content_hub_bundle_components(
        _merge_components(domain, page_id, payloads["sharedComponents"], payloads["pageComponents"]),
        article_bundle,
    )
    i18n_payload = _merge_content_hub_bundle_i18n(
        _merge_i18n(domain, page_id, lang, payloads["sharedI18n"], payloads["pageI18n"]),
        article_bundle,
    )
    return {
        "version": 1,
        "domain": domain,
        "pageId": page_id,
        "sourceStage": "published",
        "environment": environment,
        "versionId": version_id,
        "lang": lang,
        "generatedAt": now_iso(),
        "route": route,
        "lifecycle": lifecycle,
        "siteConfig": _public_site_config(payloads["siteConfig"]),
        "pageConfig": page_config,
        "components": components_payload,
        "variables": variables_payload,
        "angoraCombos": _merge_angora_combos(domain, page_id, payloads["sharedAngoraCombos"], payloads["pageAngoraCombos"]),
        "i18n": i18n_payload,
        "metadata": {
            "requestId": request_id,
            "requestedDomain": requested_domain,
            "resolvedAlias": resolved_alias,
            "environment": environment,
            "resolvedPath": path,
            "statusCode": 404 if not_found_status else 200,
            "notFound": not_found_status,
            "fallbackFromDomain": fallback_from_domain,
            "contentHubs": _public_content_hubs(site_metadata) or _public_content_hubs({"domain": domain, **payloads.get("siteConfig", {})}),
        },
    }


def _canonical_not_found_response(
    *,
    request_id: str,
    requested_domain: str,
    path: str,
    lang: str,
    environment: str,
    fallback_from_domain: Optional[str],
) -> Dict[str, Any]:
    domain = CANONICAL_NOT_FOUND_DOMAIN
    metadata = load_item(CONFIG_TABLE_NAME, site_pk(domain))
    if not isinstance(metadata, dict):
        return not_found("Canonical 404 metadata not found", domain=domain, requestedDomain=requested_domain)

    lifecycle = metadata.get("lifecycle") if isinstance(metadata.get("lifecycle"), dict) else {"status": "active"}
    published_pointer = _published_pointer(metadata, environment)
    effective_environment = environment
    if not published_pointer and environment != "production":
        published_pointer = _published_pointer(metadata, "production")
        effective_environment = "production"
    if not published_pointer:
        return not_found("Canonical 404 published configuration not found", domain=domain, environment=environment)

    version_id = str(published_pointer.get("versionId") or "").strip()
    prefix = str(published_pointer.get("prefix") or default_version_prefix(domain, version_id)).strip()
    if not prefix:
        return not_found("Canonical 404 published configuration prefix is missing", domain=domain)

    site_config = _load_payload(CONFIG_PAYLOADS_BUCKET_NAME, prefix, f"{domain}/site-config.json")
    page_id = _resolve_not_found_page_id(metadata, site_config) or "not-found"
    route = _resolve_route(metadata, site_config, "/404")
    payloads = _load_runtime_payloads(domain, prefix, page_id, lang, site_config)
    if not payloads:
        return not_found("Canonical 404 payload set is incomplete", domain=domain, pageId=page_id, versionId=version_id)

    return ok(_published_bundle(
        request_id=request_id,
        requested_domain=requested_domain,
        domain=domain,
        resolved_alias=None,
        environment=effective_environment,
        version_id=version_id,
        prefix=prefix,
        path=path,
        lang=lang,
        lifecycle=lifecycle,
        site_metadata=metadata,
        route=route,
        page_id=page_id,
        payloads=payloads,
        not_found_status=True,
        fallback_from_domain=fallback_from_domain,
    ))


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    request_id = get_request_id(context)
    requested_domain = _resolve_domain(event)
    requested_environment = _requested_environment_override(event)
    path = _resolve_path(event)
    lang = get_query_value(event, "lang") or "en"

    if not requested_domain:
        return bad_request("Missing domain. Provide query parameter 'domain' or a host header.")

    try:
        domain, metadata, resolved_alias, environment = _resolve_site_metadata(requested_domain)
        if requested_environment and not resolved_alias:
            environment = requested_environment

        if not metadata:
            return _canonical_not_found_response(
                request_id=request_id,
                requested_domain=requested_domain,
                path=path,
                lang=lang,
                environment=requested_environment or _infer_environment_from_domain(requested_domain),
                fallback_from_domain=requested_domain,
            )

        lifecycle = metadata.get("lifecycle") if isinstance(metadata.get("lifecycle"), dict) else {"status": "active"}

        if str(lifecycle.get("status") or "active") != "active":
            route = _match_route(metadata, path)
            page_id = str((route or {}).get("pageId") or metadata.get("defaultPageId") or "default").strip() or "default"
            bundle = _fallback_bundle(domain, page_id, metadata, lifecycle)
            bundle["environment"] = environment
            return ok(bundle)

        published_pointer = _published_pointer(metadata, environment)
        if not published_pointer:
            return _canonical_not_found_response(
                request_id=request_id,
                requested_domain=requested_domain,
                path=path,
                lang=lang,
                environment=environment,
                fallback_from_domain=domain,
            )

        version_id = str(published_pointer.get("versionId") or "").strip()
        prefix = str(published_pointer.get("prefix") or default_version_prefix(domain, version_id)).strip()
        if not prefix:
            return not_found("Published configuration prefix is missing", domain=domain)

        site_config = _load_payload(CONFIG_PAYLOADS_BUCKET_NAME, prefix, f"{domain}/site-config.json")
        site_config = _merge_content_hub_runtime_indexes(site_config, lang, environment)
        if not site_config:
            return _canonical_not_found_response(
                request_id=request_id,
                requested_domain=requested_domain,
                path=path,
                lang=lang,
                environment=environment,
                fallback_from_domain=domain,
            )

        route = _resolve_route(metadata, site_config, path)
        should_render_not_found = False
        article_bundle = None
        if route:
            page_id = str(route.get("pageId") or _resolve_default_page_id(metadata, site_config)).strip() or "default"
        elif path == "/":
            page_id = _resolve_default_page_id(metadata, site_config)
        else:
            page_id = _resolve_not_found_page_id(metadata, site_config)
            should_render_not_found = True
            route = _resolve_route(metadata, site_config, "/404")

        if not should_render_not_found and _is_content_hub_article_path(site_config, path):
            article_bundle = _content_hub_bundle_for_path(site_config, path, lang, environment)
            if not article_bundle:
                page_id = _resolve_not_found_page_id(metadata, site_config)
                should_render_not_found = True
                route = _resolve_route(metadata, site_config, "/404")

        if should_render_not_found and not page_id:
            return _canonical_not_found_response(
                request_id=request_id,
                requested_domain=requested_domain,
                path=path,
                lang=lang,
                environment=environment,
                fallback_from_domain=domain,
            )

        payloads = _load_runtime_payloads(domain, prefix, page_id, lang, site_config)
        if not payloads and should_render_not_found:
            return _canonical_not_found_response(
                request_id=request_id,
                requested_domain=requested_domain,
                path=path,
                lang=lang,
                environment=environment,
                fallback_from_domain=domain,
            )

        if not payloads:
            return not_found(
                "Published payload set is incomplete",
                domain=domain,
                pageId=page_id,
                versionId=version_id,
            )

        return ok(_published_bundle(
            request_id=request_id,
            requested_domain=requested_domain,
            domain=domain,
            resolved_alias=resolved_alias,
            environment=environment,
            version_id=version_id,
            prefix=prefix,
            path=path,
            lang=lang,
            lifecycle=lifecycle,
            site_metadata=metadata,
            route=route,
            page_id=page_id,
            payloads=payloads,
            not_found_status=should_render_not_found,
            article_bundle=article_bundle if not should_render_not_found else None,
        ))
    except Exception as exc:
        log("ERROR", "Runtime bundle read failed", requestId=request_id, domain=requested_domain, path=path, error=str(exc))
        return server_error()
