# Published article body projection — 2026-11-20 CT

A valid static article body could remain in `variables.contentHub.currentArticle.articleContent` even after an editorial package supplied a newer `variables.articleContent`. The Angular reader preserves the indexed body when it is valid, so migrated HTML articles could render the old text despite a successful publication.

Runtime Read now copies the published package's effective body into the matching current-article projection. The copy replaces the whole body, preserving Delta without inheriting static HTML, and uses the already normalized body for an authorized shared reader. An internal loader-created binding must match article ID, path and locale in both the original variables and the merged result. The binding is never serialized. Missing packages or bodies preserve the authored fallback. A declared foreign package locale is rejected; a legacy package without a locale continues to use its validated storage key.

Verification: 15 focused regressions cover HTML, Delta, shared-owner normalization, missing/invalid bodies, identity/path/locale boundaries, legacy locale compatibility, marker isolation, input/cache immutability and editable current-article overrides. The complete offline Python suite passed 227 tests. Local SSR with unchanged frontend MAIN reproduced both affected legacy bodies before the projection and rendered their exact newly published body after it; anonymous desktop/mobile hydration passed all four cases without JavaScript errors.

This entry records implementation and local verification only. No production deployment is claimed here.
