import os
from typing import Any, Dict, Optional

from zoolanding_lambda_common import (
    alias_pk,
    bad_request,
    default_version_prefix,
    get_header_value,
    get_query_value,
    get_request_id,
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


def _resolve_site_metadata(domain: str) -> tuple[str, Optional[Dict[str, Any]], Optional[str]]:
    canonical_domain = normalize_domain(domain)
    if not canonical_domain:
        return "", None, None

    metadata = load_item(CONFIG_TABLE_NAME, site_pk(canonical_domain))
    if isinstance(metadata, dict):
        return canonical_domain, metadata, None

    alias_item = load_item(CONFIG_TABLE_NAME, alias_pk(canonical_domain), "SITE")
    if not isinstance(alias_item, dict):
        return canonical_domain, None, None

    target_domain = normalize_domain(alias_item.get("domain"))
    if not target_domain:
        return canonical_domain, None, None

    metadata = load_item(CONFIG_TABLE_NAME, site_pk(target_domain))
    if not isinstance(metadata, dict):
        return canonical_domain, None, None

    aliases = _normalize_aliases(metadata.get("aliases"))
    if canonical_domain not in aliases:
        return canonical_domain, None, None

    return target_domain, metadata, canonical_domain


def _match_route(metadata: Dict[str, Any], path: str) -> Optional[Dict[str, Any]]:
    for route in metadata.get("routes", []):
        if not isinstance(route, dict):
            continue
        if normalize_route_path(route.get("path", "/")) == path:
            return route
    return None


def _load_payload(bucket: str, prefix: str, relative_path: str) -> Optional[Dict[str, Any]]:
    key = join_s3_key(prefix, relative_path)
    return load_json_from_s3(bucket, key)


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


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    request_id = get_request_id(context)
    requested_domain = _resolve_domain(event)
    path = _resolve_path(event)
    lang = get_query_value(event, "lang") or "en"

    if not requested_domain:
        return bad_request("Missing domain. Provide query parameter 'domain' or a host header.")

    try:
        domain, metadata, resolved_alias = _resolve_site_metadata(requested_domain)
        if not metadata:
            return not_found("Site metadata not found", domain=requested_domain)

        lifecycle = metadata.get("lifecycle") if isinstance(metadata.get("lifecycle"), dict) else {"status": "active"}
        route = _match_route(metadata, path)
        page_id = str((route or {}).get("pageId") or metadata.get("defaultPageId") or "default").strip() or "default"

        if str(lifecycle.get("status") or "active") != "active":
            bundle = _fallback_bundle(domain, page_id, metadata, lifecycle)
            return ok(bundle)

        published_pointer = metadata.get("published") if isinstance(metadata.get("published"), dict) else None
        if not published_pointer:
            return not_found("Published configuration not found", domain=domain)

        version_id = str(published_pointer.get("versionId") or "").strip()
        prefix = str(published_pointer.get("prefix") or default_version_prefix(domain, version_id)).strip()
        if not prefix:
            return not_found("Published configuration prefix is missing", domain=domain)

        site_config = _load_payload(CONFIG_PAYLOADS_BUCKET_NAME, prefix, f"{domain}/site-config.json")
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
            return not_found(
                "Published payload set is incomplete",
                domain=domain,
                pageId=page_id,
                versionId=version_id,
            )

        bundle = {
            "version": 1,
            "domain": domain,
            "pageId": page_id,
            "sourceStage": "published",
            "versionId": version_id,
            "lang": lang,
            "generatedAt": now_iso(),
            "route": route,
            "lifecycle": lifecycle,
            "siteConfig": site_config,
            "pageConfig": page_config,
            "components": _merge_components(domain, page_id, shared_components, page_components),
            "variables": _merge_variables(domain, page_id, shared_variables, page_variables),
            "angoraCombos": _merge_angora_combos(domain, page_id, shared_angora_combos, page_angora_combos),
            "i18n": _merge_i18n(domain, page_id, lang, shared_i18n, page_i18n),
            "metadata": {
                "requestId": request_id,
                "requestedDomain": requested_domain,
                "resolvedAlias": resolved_alias,
                "resolvedPath": path,
                "bucket": CONFIG_PAYLOADS_BUCKET_NAME,
                "prefix": prefix,
            },
        }

        return ok(bundle)
    except Exception as exc:
        log("ERROR", "Runtime bundle read failed", requestId=request_id, domain=requested_domain, path=path, error=str(exc))
        return server_error()
