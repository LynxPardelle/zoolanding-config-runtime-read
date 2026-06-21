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
CANONICAL_NOT_FOUND_DOMAIN = os.getenv("CANONICAL_NOT_FOUND_DOMAIN", "zoolandingpage.com.mx")


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
) -> Dict[str, Any]:
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
        "siteConfig": payloads["siteConfig"],
        "pageConfig": payloads["pageConfig"],
        "components": _merge_components(domain, page_id, payloads["sharedComponents"], payloads["pageComponents"]),
        "variables": _merge_variables(domain, page_id, payloads["sharedVariables"], payloads["pageVariables"]),
        "angoraCombos": _merge_angora_combos(domain, page_id, payloads["sharedAngoraCombos"], payloads["pageAngoraCombos"]),
        "i18n": _merge_i18n(domain, page_id, lang, payloads["sharedI18n"], payloads["pageI18n"]),
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
        if route:
            page_id = str(route.get("pageId") or _resolve_default_page_id(metadata, site_config)).strip() or "default"
        elif path == "/":
            page_id = _resolve_default_page_id(metadata, site_config)
        else:
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
        ))
    except Exception as exc:
        log("ERROR", "Runtime bundle read failed", requestId=request_id, domain=requested_domain, path=path, error=str(exc))
        return server_error()
