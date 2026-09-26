# Docker-powered HK Traffic Sign Assistant — implementation plan

## Status and resumption notes

- **Status (2026-09-24):** grounded local chat, page actions, and a recorded DeepSeek live check are implemented. Human sign-name approval remains open.
- **Agreed goal:** add an agent-enabled, locally hosted Docker edition of the existing static website.
- **Current limits:** all top-100 sign names have draft bilingual proposals, but every one still needs human approval. No label is verified.
- The backend API, Docker configuration, assistant panel, three configurable cloud chat routes, and 26 place reference points are implemented. The 60-question DeepSeek record is in `docs/evaluations/`. This remains a pilot while semantic sign search has no approved labels.
- Docker Desktop was unavailable on 2026-09-19. It became available on 2026-09-20; both images built and both containers passed their health checks. See the evidence below.
- No commit, image publication, or public deployment has been made.

## 1. Agreed scope

The user selected:

| Decision | Agreed direction |
|---|---|
| Model hosting | Cloud-first, with an interface for a future local-model adapter |
| First release | Core assistant: sign search, map tools, downloads, SVG conversion |
| Language support | English and Traditional Chinese |
| Website editions | Existing GitHub Pages site plus an enhanced local Docker edition |
| Deferred features | TPDM document Q&A, photo identification, advanced dataset analysis |

Target launch experience, once Docker is available:

```sh
docker compose up --build -d
```

Open `http://localhost:8517` to use the enhanced edition. Starting Docker does not modify or automatically enhance the public GitHub Pages URL.

### First-release capabilities

1. Find signs by code or verified bilingual descriptions and aliases.
2. Display sign previews, available metadata, and SVG/DXF download buttons.
3. Find surveyed traffic signs near a supported place or selected map point.
4. Centre the map, filter codes, and highlight query results.
5. Upload an SVG, convert it using the existing converter, and explain actual warnings.
6. Continue ordinary browsing, downloads, and local tools when the model is unavailable.

This is one assistant choosing among deterministic tools, rather than a collection of collaborating agents.

## 2. Repository evidence

| Existing component | Current behavior and integration opportunity |
|---|---|
| `site/index.html` | Static sign gallery; add an optional assistant entry point |
| `site/map.html` | Static Leaflet map; reuse the same assistant panel |
| `site/index.json` | Generated manifest of codes, categories, file paths, SVG dimensions, and file sizes |
| `site/assets/app.js` | Code substring search, category filtering, and incremental rendering; functions enclosed in an IIFE |
| `site/assets/map.js` | Lazy split-cell loading, map rendering, code filtering, and hash-based view links; functions enclosed in an IIFE |
| `site/assets/dxf-download.js` | Existing compressed-download enhancement to preserve |
| `site/map-data/` | Surveyed sign records stored as `[code, longitude, latitude, angle]` |
| `scripts/build_site.py` | Generates the manifest and copies/converts drawing assets |
| `scripts/build_map_data.py` | Builds geographic cells and subcells, indexed by `cells` and `splits` |
| `src/svg2dxf/cli.py` | Shared `convert_file()` function returning conversion statistics and warnings |
| `src/svg2dxf/webapp.py` | Legacy local Flask UI: `GET /`, `POST /convert`, 20 MiB request limit |
| `tests/test_pipeline.py` | Geometry and DXF regression tests |
| `tests/test_webapp.py` | Existing Flask conversion endpoint tests |
| `.github/workflows/pages.yml` | Uploads `site/` to GitHub Pages after relevant changes |

### Important constraints

- The manifest has no semantic sign names. Reliable descriptive search requires new metadata.
- There is no place-name search index in the inspected map implementation.
- Manifest `w` and `h` are SVG viewBox dimensions, not verified physical sign dimensions.
- Marker rendering limits and clustering are presentation details, not authoritative query counts.
- The surveyed map dataset contains traffic signs. Road-marking drawings in the gallery do not imply surveyed road-marking locations.
- Some surveyed sign codes may have no downloadable artwork; count them as records while reporting artwork availability separately.
- The legacy numeric option validator rejects values <= 0 but does not reject NaN. The new service boundary must validate finite values and documented bounds.
- The earlier conversation's `TS_115` / “No entry” example was unverified and must not be used as seed data.

## 3. Architecture

```text
Browser: http://localhost:8517
                 |
                 v
      web container / Nginx
      - existing gallery and map
      - static assets and drawings
      - local runtime configuration
      - /api/* reverse proxy
                 |
                 v
      backend container / Flask + WSGI server
      - capability discovery
      - catalog and place lookup
      - geographic query tools
      - bounded agent orchestrator
      - uploads and conversion service
      - expiring sessions and artifacts
                 |
                 v
      configured cloud model API
```

### Design decisions

- Begin with two containers: `web` and `backend`.
- Reuse Flask and `convert_file()`; add a separate backend application factory without breaking `python -m svg2dxf.webapp` or the CLI.
- Keep the current plain HTML/CSS/JavaScript frontend style.
- Package static assets and backend data from the same repository revision.
- Use JSON indexes and ordinary Python search/query functions initially. No vector database or Redis is needed for the core release.
- Proposed initial provider: OpenAI official SDK, with a configurable model name. The user chose cloud-first but has not selected a particular provider/model; confirm that choice at integration time.
- Define a provider interface around normalized messages, tool calls, usage, and failures so Ollama or another provider can be added later.
- Keep agent dependencies optional for users who only install the converter.
- Proposed container runtime: Python 3.12 with tested, pinned dependencies. Reconcile the existing README's Python 3.10+ statement with `pyproject.toml`'s 3.9 minimum during setup work.

### Deployment boundary

- Publish only the web service at `127.0.0.1:8517`.
- Backend listens on its container interface but is exposed only to the internal Docker network.
- Browser and API share an origin; no public-page-to-localhost bridge is required.
- Backend alone receives model credentials. Exclude `.env`, credentials, temporary files, and irrelevant local artifacts from Git and Docker build contexts.
- Bake existing generated drawings into the appropriate image. Startup must not reconvert the collection.
- Run non-root where practical, use read-only application/data paths, and bound writable temporary storage.
- A local container does not make the application offline: cloud inference and existing map tiles need internet access.

## 4. Data preparation

### Bilingual sign metadata

Keep human-reviewed metadata separate from the generated manifest. Proposed source: `data/sign-metadata.json`; proposed generated browser supplement: `site/catalog-meta.json`.

```json
{
  "code": "TS_...",
  "name_en": "...",
  "name_zh_hant": "...",
  "aliases_en": ["..."],
  "aliases_zh_hant": ["..."],
  "subcategory": "...",
  "source": {
    "url": "...",
    "edition": "...",
    "page": "..."
  },
  "review_status": "verified"
}
```

Requirements:

- Join only to real manifest codes; fail validation on unknown or duplicate codes.
- Verify code meanings and labels against authoritative references. Record provenance and distinguish official labels from informal aliases or translations.
- Never mark model-generated labels as verified automatically.
- Begin development with approximately 50–100 reviewed signs across common categories.
- Publish counts for total drawings, verified bilingual metadata, and code-only records.
- Exact-code lookup works for all drawings even when metadata is incomplete.
- Use verified metadata for semantic retrieval; missing metadata is not evidence that a described sign does not exist.
- Full-catalog verified bilingual coverage is the final target. If it is not attainable before a pilot, label the pilot and disclose coverage rather than declaring full completion.

### Place-name index

Proposed source: `data/places.json` containing English and Traditional Chinese names, aliases, coordinates, and source references.

- Start with common districts and locations; a district centre is a reference point, not a district boundary.
- Ask for clarification when a name has multiple matches.
- Offer a selected map point or coordinates for unsupported names.
- Do not invent coordinates using the model.

### Search ranking

Normalize code separators and case. Rank exact codes first, then exact names/aliases, then broader text matches. Handle Traditional Chinese without assuming words are separated by spaces. Return bounded results with the actual matched fields and metadata coverage information.

### Geographic queries

- Select cells and subcells intersecting a bounded query area.
- Use a distance calculation for radius queries, not just a bounding box.
- Include boundary cases, return deterministic ordering, and cache data with bounded memory.
- Count matching records independently of marker caps and available artwork.
- Return `matched_total`, `returned_records`, `truncated`, `data_complete`, `query_scope`, and `dataset_revision`.
- Missing or malformed required cells make results incomplete, not a successful zero.
- Deduplicate drawing downloads by catalog code while preserving surveyed record counts.

## 5. Backend contracts

| Endpoint | Responsibility |
|---|---|
| `GET /api/health` | Backend health |
| `GET /api/capabilities` | Version, feature states, provider readiness, metadata coverage |
| `GET /api/signs` | Bounded deterministic search |
| `GET /api/signs/{code}` | Sign details and authoritative download availability |
| `GET /api/places` | Bilingual place lookup |
| `POST /api/map/query` | Radius or bounded-area query |
| `POST /api/chat` | One bounded agent turn |
| `POST /api/uploads` | Temporary SVG upload, returning an opaque upload ID |
| `POST /api/conversions` | Convert an owned upload with validated options |
| `GET /api/files/{id}` | Download an owned, unexpired output artifact |

Use structured errors with stable codes and actionable messages. Do not expose stack traces, credentials, internal paths, or raw provider errors.

### Agent tools

```text
search_signs
get_sign
resolve_place
find_nearby_signs
summarize_area
get_downloads
convert_uploaded_svg
```

- Validate tool names and argument schemas against an explicit registry.
- Application code performs counting, search, geographic calculations, and conversion.
- Download URLs are resolved from the manifest, never generated freely by the model.
- Initial `summarize_area` supports basic deterministic counts, not open-ended code execution or advanced analytics.
- No shell, arbitrary Python, arbitrary URL-fetch, or unrestricted filesystem tool.
- Uploaded SVG bytes and the full geographic dataset stay out of model prompts. Send necessary metadata, bounded tool results, and conversion warnings instead.
- Explain in setup/UI that conversations and selected context go to the configured cloud provider.

### Agent limits and state

Proposed initial defaults, to validate during implementation:

- At most four model calls and eight tool calls per user turn.
- Approximately 60 seconds total turn budget, with remaining time propagated to provider/tool calls.
- Bounded input, history, tool-result, and output sizes.
- Explicit handling for rate limits, malformed arguments, unavailable tools, and timeouts.
- Avoid unbounded retries and never automatically repeat a successful conversion after a response failure.
- Expiring server-side sessions with an opaque HttpOnly, SameSite cookie.
- Initially one WSGI worker with bounded request concurrency so in-memory sessions are consistent. Multiple workers require a shared-state design first.
- Bound session count and per-session artifacts; expire inactive state and clear temporary artifacts on restart.
- Origin/Host checks for local API access, same-origin stateful requests, and no wildcard CORS.

## 6. SVG conversion service

Reuse `convert_file()` through a shared service callable by the ordinary form and the agent tool.

Flow:

1. Validate and temporarily store the uploaded SVG.
2. Return a session-scoped upload ID.
3. Validate options and run conversion in a separate, terminable process.
4. Return statistics, warnings, and a session-scoped output download URL.
5. Expire uploads and outputs on a documented TTL and clean up failures.

Requirements:

- Coordinate Nginx and Flask upload limits with the existing 20 MiB policy, accounting for multipart overhead.
- Require finite numeric values and documented safe ranges for tolerance and scale.
- Inspect parser behavior and reject XML entity declarations and unsupported external resources before conversion.
- Do not inline arbitrary uploaded SVG markup into the application DOM.
- Start with one concurrent conversion, a bounded queue or explicit busy response, and a hard process timeout.
- Bound temporary storage and conversion resources.
- Preserve geometry regression behavior and useful warnings, including text that needs conversion to outlines.
- Do not claim a physical size from the SVG viewBox; request calibration when needed.

## 7. Frontend integration

### Progressive activation

- Add a relative runtime configuration resource whose static default disables agent features.
- The Docker web server overrides that resource to enable the local API.
- Only then probe `/api/capabilities`; validate status, JSON, and API version.
- Respect GitHub Pages project subpaths when resolving resources.
- Missing model credentials disable chat, not deterministic search or conversion.
- Backend failures leave normal gallery/map/download functionality usable and show an accurate assistant status.

### Assistant panel

Provide a reusable, responsive side panel on gallery and map pages:

- English/Traditional Chinese interface labels and response language choice.
- Chat input, search results, previews, source/review information, and download buttons.
- Upload controls and ordinary conversion options usable without AI.
- Progress, retry, reset, and cancellation/stale-response handling.
- Keyboard focus management, accessible labels, and mobile layout.
- Text-safe rendering of model output and warnings.
- Explicit download buttons rather than relying on asynchronous automatic downloads blocked by browsers.

### Page action bridge

Expose narrow commands from the existing gallery/map closures:

```text
Set exact gallery result codes
Centre map at coordinates
Apply exact sign-code filters
Highlight query radius/results
Show validated download cards
Read selected map point / current query context
```

- Validate action types, codes, and coordinate bounds in the frontend.
- Do not execute model-supplied JavaScript or arbitrary navigation URLs.
- Persist a one-time pending action for gallery-to-map navigation and apply it only after destination data is ready.
- Acknowledge actual application success; distinguish suggested, pending, applied, and failed actions.
- Clear stale pending actions and prevent an older response from overwriting a newer user interaction.
- Preserve the current download compression enhancement and map loading behavior.

## 8. Implementation milestones

Each milestone is a reviewable change set. Paths below are proposed, not existing implementation claims.

### M1 — Contracts and backend foundation

**Dependencies:** none.

**Context:** reuse the Python package and Flask while preserving the legacy CLI/web UI.

**Tasks:**

- Add a backend factory under `src/svg2dxf/server/`.
- Define capability, search, query, chat, and artifact schemas.
- Define provider/tool interfaces, error contracts, configuration, and session lifecycle.
- Add backend tests for the new contracts and no-key startup.

**Verification:** existing `python -m pytest tests/` plus new contract tests.

**Exit:** backend starts without credentials and reports unavailable chat accurately; old converter tests pass.

**Rollback:** remove the new entry point/optional dependencies; legacy entry points remain usable.

### M2 — Docker website and working conversion

**Dependencies:** M1.

**Context:** serve the existing website and API together on localhost; no model required.

**Tasks:**

- Add web/backend Dockerfiles, Compose, Nginx proxy configuration, health checks, `.dockerignore`, and credential placeholders.
- Add runtime feature configuration and API capability detection.
- Expose uploads, conversion, and downloads through the new shared service.
- Add a basic conversion form, finite-number validation, worker timeout, ownership checks, and cleanup.

**Verification:** Compose configuration/build/start checks; new conversion tests; valid DXF readback using `ezdxf`; no-key browser smoke test.

**Exit:** clean launch serves gallery/map and converts an uploaded SVG without AI.

**Rollback:** stop the local stack; static edition and legacy converter still function.

### M3 — Bilingual metadata and places

**Dependencies:** M1 schemas; may proceed alongside M2.

**Context:** existing manifest lacks semantic labels; map data lacks place names.

**Tasks:**

- Establish authoritative references and provenance format.
- Add metadata/gazetteer sources, validation, generation, and coverage reporting.
- Review approximately 50–100 pilot signs and a practical place-name seed set.
- Build English and Traditional Chinese aliases without assuming whitespace tokenization.

**Verification:** schema validation, all codes joined to manifest, reviewed bilingual query fixtures, clear unknown-name behavior.

**Exit:** pilot descriptions retrieve expected signs in both languages; unreviewed records stay code-only.

**Rollback:** discard the generated supplement while preserving code-only manifest search.

### M4 — Deterministic search and geographic tools

**Dependencies:** M1 and M3.

**Context:** real tool results are the foundation for agent answers; display counts are insufficient.

**Tasks:**

- Implement search, details, place lookup, and manifest-based download resolution.
- Implement bounded radius/area queries over existing cells/subcells.
- Add caching, deterministic sorting, pagination/truncation, and completeness metadata.
- Test absent artwork separately from absent surveyed records.

**Verification:** API/unit tests for exact codes, bilingual aliases, radius boundaries, split cells, missing data, and counts independent of rendering caps.

**Exit:** all tools work reproducibly without an LLM.

**Rollback:** disable tool capability flags; original frontend behavior remains available.

### M5 — Bounded cloud agent

**Dependencies:** M2 and M4.

**Context:** tools and upload ownership are implemented before granting the model access.

**Tasks:**

- Confirm provider/model and implement the first adapter.
- Implement bounded turn execution, typed tool dispatch, compact context, and bilingual responses.
- Connect owned upload references to conversion.
- Handle provider timeouts, rate limits, malformed calls, and budget exhaustion.

**Verification:** mocked-provider tests covering successful multi-step flows, unknown tools, invalid arguments, turn limits, and failures; opt-in live-provider smoke test later.

**Exit:** agent completes search → map → download and upload → conversion using real tool outputs.

**Rollback:** disable chat/provider configuration; deterministic tools continue working.

### M6 — Assistant panel and actual page actions

**Dependencies:** M2, M4, and M5.

**Context:** add a narrow bridge to `app.js`/`map.js`, rather than unrestricted browser automation.

**Tasks:**

- Build bilingual panel, result cards, upload UI, reset, and progress states.
- Add typed gallery/map commands and action acknowledgements.
- Handle cross-page readiness, stale turns, pending action expiry, and user overrides.
- Add mobile/keyboard support and graceful provider/backend failure states.

**Verification:** browser tests in static and local modes, mocked agent flows, cross-page navigation, downloads, upload conversion, and failure recovery.

**Exit:** actions change actual page state and the assistant reflects their success or failure accurately.

**Rollback:** runtime configuration disables panel/action integration.

### M7 — Coverage, release checks, and documentation

**Dependencies:** M2–M6.

**Context:** useful pilot functionality is not equivalent to complete semantic catalog coverage.

**Tasks:**

- Expand reviewed metadata toward full-catalog bilingual coverage; explicitly label any pilot shortfall.
- Complete regression, API, browser, and container checks.
- Add deterministic CI and an opt-in live-model evaluation.
- Document prerequisites, `.env` configuration, startup, shutdown, updates, coverage, privacy behavior, and troubleshooting.
- Record actual test evidence and remaining gaps.

**Verification:** full suite, container smoke tests, clean-setup walkthrough, and reviewed bilingual evaluation prompts.

**Exit:** documented first-release checklist passes, or a clearly scoped pilot is reported with unresolved gates.

**Rollback:** retain the last passing local image/revision and disable failing capabilities; publishing images is a separate user-approved action.

### Dependency graph

```text
M1 ──> M2 ───────────┐
 │                  v
 └──> M3 ──> M4 ──> M5 ──> M6 ──> M7
```

M2 and M3 can be developed independently once M1 contracts are stable. They need coordinated reviews if modifying shared packaging or schemas.

## 9. Verification strategy

### Existing regression baseline

```sh
python -m pytest tests/
```

Preserve clean filled regions, outline behavior, intrinsic holes, painter order, colors after layer moves, and text warnings.

### New API/tool guarantees

- Equivalent code forms: `TS101`, `TS 101`, `TS_101`.
- Verified English and Traditional Chinese aliases retrieve equivalent targets.
- Unknown/ambiguous names produce honest results or clarification.
- Exact-code search covers the existing catalog despite metadata gaps.
- Radius queries and split-cell boundaries produce correct results.
- Counts are independent of marker caps and downloadable drawing-type counts.
- Missing cells report incomplete data.
- Invalid uploads/options, NaN/infinity, excessive requests, and external-resource references fail safely.
- Conversion timeouts terminate work and clean up files.
- Sessions cannot download each other's artifacts; expired artifacts are inaccessible.
- Missing keys/provider failures leave deterministic features available.
- Model/tool budgets and malformed outputs cannot bypass the registry.

### Browser scenarios

1. Static site hosted under a project subpath: no local agent dependency.
2. Docker edition without a key: catalog/map/ordinary conversion work.
3. Mocked agent: real gallery and map actions with correct acknowledgements.
4. Gallery-to-map navigation with delayed data loading.
5. Valid upload and DXF download.
6. Invalid upload and backend failure during a request.
7. Stale responses and reset during navigation.
8. Mobile layout and keyboard-only operation.

### Agent evaluation

Prepare approximately 60 reviewed prompts across both languages, covering code search, descriptive search, place queries, map selection, downloads, conversion, ambiguity, and failure cases.

Evaluate correct retrieval, tool choice, query scope, action execution, and valid download links. Treat invented codes/links and unsupported factual counts as failures. Regular CI uses mocked provider responses and deterministic fixtures; paid live-model evaluation is opt-in and separately reported.

### Docker checks, when available

```sh
docker compose config --quiet
docker compose build
docker compose up -d --wait
```

Verify health, restart behavior, no-key startup, same-origin routing, temporary cleanup, and that frontend assets/images do not contain provider credentials. Measure actual container resource requirements before documenting minimum hardware.

## 10. Definition of done

- [ ] Docker launches the enhanced website using documented setup.
- [ ] Public static gallery/map/downloads remain functional.
- [ ] English and Traditional Chinese search works over reviewed metadata.
- [ ] Every drawing remains accessible by exact code.
- [ ] Metadata coverage is explicit and meets the declared release target.
- [ ] Geographic counts and completeness come from dataset queries.
- [ ] Browser actions apply successfully or return accurate failure status.
- [ ] Downloads resolve only to available assets or owned generated files.
- [ ] Uploaded SVGs produce valid DXFs with useful warnings.
- [ ] Model outages do not disable ordinary website features.
- [ ] Credentials remain backend-only.
- [ ] Sessions, uploads, and artifacts are bounded and expire predictably.
- [ ] Existing regression and new API/browser/container checks pass.
- [ ] Documentation includes actual evidence, setup, limitations, and recovery instructions.

## 11. Later extensions

After the core release:

1. **Ollama adapter:** choose and evaluate a tool-capable model; document measured RAM/GPU/download requirements and container networking.
2. **TPDM document Q&A:** ingest authoritative editions, preserve page citations, and test retrieval/answer support. Add a retrieval store only when justified.
3. **Photo recognition:** compare uploaded images against verified catalog candidates and show uncertainty; evaluate confusing sign variants.
4. **Advanced dataset analysis:** add specific deterministic aggregation/export tools before considering general analytical execution.
5. **Published container images:** optional registry workflow and versioned release instructions, after explicit authorization.

## 12. References and open decisions

### Reference agent patterns

- [500-AI-Agents-Projects](https://github.com/ashishpatel26/500-AI-Agents-Projects): catalog of patterns and examples, not a drop-in static website plugin.
- [Customer support agent](https://github.com/ashishpatel26/500-AI-Agents-Projects/tree/main/agents/13-customer-support-agent): conversational assistance and tool/retrieval concepts.
- [PDF Q&A agent](https://github.com/ashishpatel26/500-AI-Agents-Projects/tree/main/agents/03-pdf-qa-agent): reference for the later document feature.
- [Data analysis agent](https://github.com/ashishpatel26/500-AI-Agents-Projects/tree/main/agents/08-data-analysis-agent): natural-language analysis inspiration. Its model-generated Python execution is not the proposed query implementation.
- [Project README](../README.md): current converter/site usage and Transport Department dataset references.

### Decisions to resolve during implementation

- Initial cloud provider and model, with measured tool-call support and cost.
- Authoritative metadata sources, edition/page references, and actual achievable bilingual coverage.
- Exact session/artifact TTLs, conversion parameter bounds, process timeout, and resource limits, based on tests.
- Whether the first deliverable is a clearly labeled pilot or full-catalog semantic release.
- Supported host platforms and container hardware requirements, once Docker can be tested.

### Updating this plan

Mark milestones complete only with actual verification evidence. If scope, contracts, or dependencies change, update the affected sections and note the reason here. Preserve unresolved blockers instead of silently weakening exit criteria.

**Current next step:** obtain human review of the source-checked labels, expand bilingual coverage, and run opt-in live model checks when credentials are available. Broader browser regression remains open.

### 2026-09-19 pilot evidence

- `python -m pytest tests/ -q`: 25 passed, including catalog, split-cell, session ownership, conversion readback, mocked tool calling, conversion idempotency, and an owned-upload chat flow.
- `docker compose config --quiet`: passed. Image build and startup were not run because Docker Desktop did not start; `docker info` still could not connect to `dockerDesktopLinuxEngine`. Docker's backend log reports that it could not rename `sailor-ingest.sock` to a stale name. Starting the Docker service from this session was denied by Windows.
- Browser smoke test used a temporary same-origin Flask server. Static mode showed the original 1,327 drawing gallery with no assistant button. Local mode showed the panel, found `TS_101` by its sourced English label and `TS_102` by its sourced Chinese label, filtered the gallery to one drawing, queried 2,080 surveyed records near the Mong Kok reference point, navigated to the map, and converted an uploaded SVG with a DXF download link. The cross-page acknowledgement and a 390-pixel mobile panel were checked. Browser console reported no errors. This tests application behavior, not the unbuilt Nginx image.
- Metadata coverage is 0/1,327 human-verified bilingual labels and 2 source-checked labels pending human review. The place index has 8 reference points from the Lands Department location search API. Full semantic coverage and the planned 60-prompt bilingual evaluation remain open.
- Cloud chat was tested with a mocked provider. A live cloud-model call was not made because no model credentials were supplied.

| Milestone | Evidence-based state |
|---|---|
| M1 backend contracts | Implemented and covered by local tests. |
| M2 Docker and conversion | Both images build and containers become healthy; upload, conversion, and download pass through Nginx. |
| M3 bilingual metadata and places | Eight sourced place centres; two sourced bilingual labels pending human review. Coverage target open. |
| M4 deterministic tools | Search, details, place lookup, radius/area query, and completeness metadata pass local tests. |
| M5 cloud agent | Tool registry, limits, mocked search and conversion flows pass; live provider check pending. |
| M6 assistant panel | Docker browser search, gallery action, place-to-map action, and conversion pass. A no-key chat state bug was fixed; broader regression scenarios remain open. |
| M7 release | CI, setup, privacy, and troubleshooting docs added; container build/start pass. Coverage and live evaluation gates remain open. |

### 2026-09-20 Docker evidence

- `docker info`, `docker compose config --quiet`, `docker compose build`, and `docker compose up -d --wait` passed. Both containers reported healthy. The web service was bound to `127.0.0.1:8517`; the backend had no published port.
- Through Nginx, `/api/health`, `/api/capabilities`, sign search, and map query returned HTTP 200. Uploading `TS_101.svg`, converting it, and downloading the DXF returned HTTP 200; `ezdxf` read 42 model-space entities. A request without the session cookie received HTTP 404 for that DXF.
- A cross-origin map request received HTTP 403. The owned DXF returned HTTP 200 before a backend restart and HTTP 404 after it; both containers returned to healthy state.
- In the Docker browser, searching “stop” found `TS_101`, and the gallery narrowed to one drawing. Choosing Mong Kok reported 2,080 surveyed records; opening the map applied its centre and radius after the map loaded. The browser conversion control produced a DXF download link.
- A browser race left chat controls enabled after the map action when no key was configured. Capability loading now runs independently of cancellable search requests, and chat starts disabled. A fresh browser retest confirmed the controls remain disabled after the same gallery-to-map flow. Versioned assistant asset URLs prevent the old script from being reused after this update.
- `ezdxf` first logged that its optional font cache could not be written under the read-only home directory. `XDG_CACHE_HOME` now points to temporary storage; the warning no longer appears after container recreation.
- The live cloud-model path remains untested because no API key was supplied. Metadata coverage remains 0 human-verified bilingual labels, 2 source-checked labels awaiting review, and 1,325 code-only drawings.

### 2026-09-20 provider options

- The backend can select OpenAI, DeepSeek, or Vercel AI Gateway through `AI_PROVIDER` and a matching key/model in `.env`. Only the chosen route is active. All three use the bounded tool-calling loop; DeepSeek uses its documented non-thinking Chat Completions request form.
- Provider selection, API request options, and capability reporting pass mocked-client tests. The rebuilt Docker site shows “Provider: OpenAI” and keeps chat disabled without a key. DeepSeek and Vercel configurations each report the expected provider and model inside the Linux container when given dummy keys; no request was sent to either service. No live provider request has been made because no real API key was supplied. The frontend displays the configured provider and active model without showing a key.

Pilot scope change: the two source-checked labels can be found by description,
but each result says human review is pending. They are excluded from the
`verified_bilingual` count. This lets the pilot exercise semantic search without
claiming that AI-sourced labels have completed human review. The release target
of approximately 50–100 human-reviewed signs remains open.

The proposed `site/catalog-meta.json` supplement was not generated. The Docker
panel gets label data from the backend API, and the public static site remains
code-only. This keeps unreviewed pilot labels off the public download site.

### 2026-09-25 approval update

The project owner approved all 100 frozen sign entries in the Codex chat.
`data/sign-metadata.json` now has 100 verified bilingual labels, each with a
reviewer and approval time. The remaining 1,227 drawings are code-only.
The five review batches show their approved state. A new 60-question live
DeepSeek run, including English and Traditional Chinese name searches, passed
29/30 English and 30/30 Chinese tasks. It found no invented visible facts.
The record is `docs/evaluations/deepseek-20260924-085242.json`.
The English miss asked for help but received sign search. The help routing
instruction was clarified and a focused live retest passed. The retest is in
`docs/evaluations/deepseek-help-followup.json`.
