# AI Development Handbook

## 1. Purpose and scope

This is the English handover document for AI-assisted maintenance of the Customs Suspect Identification System. Read this file before planning, reviewing, changing, testing, or deploying the repository. It is a development aid, not a replacement for the Chinese source requirements.

At the original handbook creation, the project had no Git commit history. Git publication and subsequent history changes are recorded in CHG-0012 through CHG-0016; this introductory observation is historical, not the current repository state. The earlier ledger below is a reconstruction from available source files, local implementation notes, test evidence, and user-reported issues. It cannot recover every historical line edit, precise timestamp, or unrecorded failed attempt. Do not present a reconstructed item as a complete audit trail.

Facts are marked as `OBSERVED` when they were checked in source, tests, runtime, or dated records. `HISTORICAL` means a prior work record exists but was not re-run for this documentation change. `OPEN` is an unverified, deferred, or external dependency. Requirement documents describe target behavior; they do not prove implementation.

## 2. Mandatory reading order

1. Read `AGENTS.md`, this document, `docs/DEVELOPMENT_HISTORY_ZH.md`, and `readme.md`.
2. Read the relevant primary requirement sections listed in the source register.
3. Inspect current frontend callers, API routes, schemas, permission checks, persistence, migrations, and tests.
4. Compare requirements, implementation, and evidence. State conflicts before changing behavior.
5. Add a new `CHG-NNNN` ledger entry in this file and the Chinese history before implementation. Update both after verification.

Never rely only on screenshots, a health endpoint, a historical note, an unmounted legacy file, or a passing unit test to claim end-to-end behavior.

## 3. Source register

| Source | Role | Version/date | Integrity snapshot on 2026-09-08 |
| --- | --- | --- | --- |
| Product Requirements Document | Product scope, roles and functional requirements | V1.3, CHG-0019, 2026-09-08 | Controlled local source, excluded from Git. SHA-256 `90496564b03be7f1b896283159ae120ab6e8f21539045cc5e0d95602dd5ffe9d` |
| API Contract | REST, JWT, WebSocket, speech, avatar and permission contract | 1.2, CHG-0019, 2026-09-08 | Controlled local source, excluded from Git. SHA-256 `ec5e88e1bfcc4478c53217bf1486289129ef0330b53bb2a117fff9d2b8dfce74` |
| Architecture Design | Target architecture and non-destructive migration design | 1.2, CHG-0019, 2026-09-08 | Controlled local source, excluded from Git. SHA-256 `da9164dea99c767f940f54b6354e3242809c26b72a1ac179ed35b78c1a6dfb57` |
| AI Technical Design | Detection, multimodal speech, safety and avatar import | 1.2, CHG-0019, 2026-09-08 | Controlled local source, excluded from Git. SHA-256 `80fb4304f51f8816c1fc04dd3c3d458106eea251e05f44937c0d870bcb1772c2` |
| User-supplied task brief PDF | Functional source, pages 1-5; user scope overrides submission requirements | Read-only source, checked 2026-09-08 | Controlled local source. SHA-256 `23ab8da5d61aa17436f6dd9c2ea04657fc44f1cd304c12ea727ded5749298999` |
| `docs/V1.2_IMPLEMENTATION.md` | Dated implementation and verification record | updated 2026-09-08 | Current status, not a requirements replacement |
| `docs/IMPLEMENTATION_BOUNDARIES.md` | Module-to-source map and implementation limits | updated 2026-09-08 | Current status plus planned V1.3 scope, not a requirements replacement |
| `backend/README.md` | Runtime, backup, dependency, and safety operations | V1.2 runtime plus CHG-0017 target notice | Operational commands remain unchanged |

The controlled sources are intentionally not in the repository. Before a change that depends on them, request authorized local access from the project owner and compare the delivered file hashes with this register. If any primary file changes, update the date and SHA-256 here and re-evaluate entries that depend on it.

The source register is updated by CHG-0019 after the partial V1.3 implementation snapshot. Their leading V1.3 sections override conflicting historical base sections; CHG-0014 enterprise branding and CHG-0015 handsome model addenda still apply where not superseded. Source paths and the supplied asset directory remain controlled local material, not public repository links. No source document being complete implies runtime implementation.

## 4. Non-negotiable system boundaries

- The current local YOLO model returns only `handsome` candidate boxes. The model-defined class is not an identity or an appearance assessment. It does not identify a person, estimate criminal probability, deduplicate people, track across cameras, or make an enforcement decision. Historical `sus` boxes remain historical records.
- Person links are manual, permission-checked associations. A retained review is not a confirmed identity or a legal conclusion.
- Current runtime remains text-only. V1.3 permits explicitly selected images and recordings only through frozen per-turn preview/confirmation; continuous camera feeds and automatic internal-chat disclosure remain forbidden. Speech and multimodal input do not authorize autonomous actions.
- CHG-0017 authorizes designs for speech, own-detection screenshot sharing and manager-controlled avatar assets. It does not authorize arbitrary file upload, web-managed YOLO weights, threshold edits, automatic vendor fallback/retry, full private-chat audit, voice cloning, lip sync or external-network messaging.
- Do not place a production database on a network file system. Do not expose development settings to a LAN by changing only the bind address.
- Do not log passwords, API keys, cookie values, request bodies, private chat bodies, raw URLs with search terms, stack traces, or user input values.

## 5. Actual implementation snapshot

### 5.1 Runtime and code layout

`OBSERVED` on 2026-09-07:

```text
Browser
  index.html -> frontend.js -> ui/*.js
  frontend.css, assets/, vendor/three
        |
Same-origin FastAPI application
  backend/app/main.py
  /api/v1 REST, /ws/events WebSocket, assistant SSE
        |
SQLite + controlled local media + one local YOLO worker path
```

- Frontend: native JavaScript ES modules. The historical design specified Vue/Vite, but CHG-0017 adopts the existing native modules as the new target; a framework rewrite is no longer required. This does not imply parity for the other V1.3 features.
- Backend: Python/FastAPI/SQLAlchemy/Alembic with SQLite. Migrations are in `backend/migrations/versions/` through `20260905_0006_v12.py`.
- Frontend entry is `index.html` -> `frontend.js` -> `ui/core.js`, `ui/detection.js`, `ui/chat.js`, `ui/assistant.js`, and `ui/admin.js`. Anonymous boot plays two static, sandboxed `/ui/intro/` pages before the login view; authenticated boot does not. Legacy `app.js`, `app-live.js`, and style files remain on disk but are not the served entry path.
- Current verified development URL is `http://127.0.0.1:8000/`. It deliberately binds to loopback in the documented launch command.
- `backend/data/`, `backend/media/`, `backend/logs/`, `backend/.venv/`, `.env`, and `node_modules/` are ignored by Git. They must not be committed as a convenience.

### 5.2 Main module map

| Area | Frontend | Backend | Notes |
| --- | --- | --- | --- |
| Auth and profile | `ui/core.js` | `endpoints/auth.py`, `services/security.py` | Cookie session, CSRF, restricted initial-password phase, profile and password change |
| Users and persons | `ui/admin.js` | `endpoints/users.py`, `endpoints/persons.py` | Object and role checks remain server-side |
| Image, camera, records | `ui/detection.js` | `endpoints/detections.py`, `records.py`, `camera.py`, `services/detection.py` | Controlled media, batches, review, derived watermarked output |
| Communications | `ui/chat.js` | `endpoints/chat.py`, `community.py` | Direct, group, public room, membership-scoped history, presence |
| Providers, agents, knowledge | `ui/admin.js` | `operations.py`, `agents.py` | Encrypted secrets, explicit test and later enablement |
| Assistant and avatar | `ui/assistant.js`, `ui/avatar.js`, `ui/markdown.js` | `assistant.py`, `assistant_events.py`, `services/llm.py`, `assistant_output.py` | Exact preview, one confirmation, controlled streaming, citations |
| Operations and big screen | `ui/admin.js` | `system.py`, `client_logs.py`, `core/logging.py` | Safe logs and record/box metrics, not person identity metrics |

### 5.3 Verified evidence snapshot

`HISTORICAL` evidence from the dated implementation record:

- 40 isolated backend tests passed on 2026-09-07.
- Frontend syntax, safe Markdown, exact message cursor merge/deduplication, and GLB structure checks passed.
- Isolated HTTP smoke tests covered login, password change, registration, idempotent group creation, messages, and static assets.
- A real local YOLO subprocess processed two synthetic images and produced readable source and derived media. This is not model-quality validation.
- Browser checks covered anonymous login landing, group creation/selection/message persistence, and page loading for the cited modules.

`OPEN`: no accepted real cloud-vendor test, formal GLB asset, physical camera acceptance, Windows acceptance, LAN HTTPS acceptance, long-run load test, log-retention job, or complete failure-injection test.

## 6. Requirement highlights and conflict resolution

1. Password policy: older user feedback requested eight characters; API Contract section 3 resolves the conflict as 12 to 128 characters. Existing password hashes are not reset by this change.
2. Login persistence: a persistent server-side cookie does not mean unlimited login. The contract is eight hours absolute and 30 minutes idle; background activity must not renew it forever.
3. Default administrator: create protected `admin` with `admin123` only when an empty system first initializes. Do not reset existing credentials or overwrite a conflicting account.
4. Camera and LAN: browser camera on a LAN normally needs trusted HTTPS. A local loopback test is not LAN acceptance.
5. Avatar: the current renderer accepts a deployment GLB only. V1.3 designs manager/super-manager import, isolated PMX-to-GLB conversion, validation and atomic activation. The supplied PMX package has noncommercial/no-redistribution notices and is not activated; asset rights are independent of enterprise branding.
6. AI: structured output and citations reduce unsupported claims but do not prove natural-language accuracy. Human review remains required.
7. Architecture: implementation extensions and deviations must be documented. CHG-0017 resolves the old Vue/Vite discrepancy at design level by retaining native modules; code remains V1.2.

### 6.1 Current V1.3 target, not implemented

- Scope: user-requested functional documentation only; no coursework submission artifacts or acceptance-evidence work. Current operational commands still target the original data paths and opaque-session code.
- Auth: signed JWT in HttpOnly customs_access Cookie, independent signing key, server-side sid/auth_version revocation, CSRF retained, one active login per account. Eight-hour absolute and thirty-minute idle limits remain; no refresh token or indefinite renewal.
- Providers: manager-only encrypted connection configuration, asynchronous vendor-specific model discovery and autofill, separate per-model capability observations, explicit tests and enablement. Ordinary users select published bindings, not shared credentials.
- Assistant: selected image/text VISION, per-turn PIPELINE ASR/text/TTS and native OMNI, frozen disclosure scope, per-stage billing/idempotency, playback state without lip sync, generation-based reset and bounded audio retention.
- Avatar: managers and super-managers upload/validate/preview/activate/rollback controlled assets. Supplied PMX is the preferred candidate, not an installed GLB; no rights to commercial use or redistribution are inferred.
- Data: planned database/customs_training.db, results/ categories, physical detect_log table; preserve record IDs, credentials, media and snapshots. Explicit initialization/migration, no silent recreation of a missing database. No data has moved in this change.
- Remaining functional targets: own-result screenshot messages, type filtering, member join/leave events, immediate logout notifications, read/received separation, scoped dashboard metrics, business logs and frame-bound display smoothing.
- Corrections: ui/detection.js still hardcodes sus for camera output despite CHG-0015's completeness wording. Do not rewrite old observations; carry this as pending implementation.
- Primary sections: PRD V13-00 through V13-09; API C13-00 through C13-09; architecture A13-01 through A13-09; AI AI13-01 through AI13-10. API enums/fields take precedence over prose examples.

## 7. Safe local operations

Run from repository root:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests -q
npm run check
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/backup_database.py backend/data/backups/before-change.db
```

The backup destination must not already exist. Database backup alone does not restore media, configuration, or program version. The HTTP smoke scripts are intentionally for a fresh isolated test service, not the active business database. Read `backend/README.md` before using them.

Do not change `APP_SECRET_KEY` in an existing installation without a backup and migration plan. It protects sessions and encrypted provider credentials. Do not publish to `0.0.0.0`, call paid cloud APIs, or reset an account while investigating a bug without explicit authority.

## 8. Change ledger

### CHG-0001 - V1.2 implementation baseline

- Status: `HISTORICAL / IMPLEMENTED`
- Problem/request: replace disconnected visual mockups with a persisted full-stack course-training system aligned to the revised V1.2 requirement set.
- Evidence and cause: repository source and `docs/V1.2_IMPLEMENTATION.md` show a FastAPI application, database migrations, native UI modules, and local assets. There is no commit history to prove the exact earlier sequence.
- Work recorded: introduced server-side auth, users, persons, controlled media, detection records/batches, camera sessions, chat, providers, agents, knowledge, assistant, operations, migrations, and front-end module routes.
- Verification: historical 40-test and smoke-test snapshot in section 5.3.
- Remaining: architecture still differs from the Vue/Vite design; external acceptance remains open.

### CHG-0002 - Authentication landing, CSRF, registration, and initial password phase

- Status: `HISTORICAL / IMPLEMENTED`
- Problem/request: service launched directly into initial-password change; login and registration produced generic load failures; later CSRF errors appeared.
- Cause: anonymous access and the restricted-password state were not sufficiently separated in the earlier flow; frontend/backend contract handling required correction. This is a historical explanation, not a reproduced incident trace.
- Work recorded: anonymous users receive the login view; only a successfully authenticated restricted session enters initial password change. Centralized same-origin API calls obtain CSRF, retry one explicit CSRF failure with the same idempotency key, and surface request IDs.
- Affected areas: `ui/core.js`, `endpoints/auth.py`, `services/security.py`, session/CSRF persistence.
- Verification: historical isolated login, registration, password-change, and anonymous landing checks.
- Remaining: test login rate limits and multi-browser session behavior under deployment conditions.

### CHG-0003 - Authentication UI cleanup and password usability

- Status: `HISTORICAL / IMPLEMENTED`
- Problem/request: remove left-side decorative bars, replace auth background, add password visibility, add profile password management, reset/repair administrator password behavior.
- Work recorded: auth pages share the approved background asset and text-focused left side; password controls use an eye button; profile includes self-service password change. New password validation is 12 to 128 characters after the V1.2 contract resolved the earlier eight-character request.
- Safety effect: password values are not documented or logged; existing hashes were preserved rather than reset as a side effect.
- Remaining: visual regression checks across target browsers were not completed.

### CHG-0004 - Session lifecycle and login persistence

- Status: `HISTORICAL / IMPLEMENTED`
- Problem/request: login state appeared to expire or behave inconsistently.
- Work recorded: server-side session validation, eight-hour absolute limit, 30-minute idle limit, account/role/password revocation, and no artificial logout when server-side logout cannot be confirmed.
- Affected areas: `services/security.py`, auth endpoints, `ui/core.js`.
- Constraint: background polling does not create permanent sessions.
- Remaining: long-lived browser and multi-device acceptance is open.

### CHG-0005 - Detection records, dashboards, and removal of example data

- Status: `HISTORICAL / IMPLEMENTED`
- Problem/request: UI displayed demonstration records, example counts, virtual users, and inconsistent table sizing.
- Work recorded: dashboard, records, and detection views were connected to database data; demo records were removed from served UI; record counts are explicitly records/boxes rather than unique people; review and manual person-link history are persisted.
- Affected areas: `ui/detection.js`, `ui/admin.js`, detection/records/person endpoints and models.
- Remaining: production data migration and full report-layout acceptance are open.

### CHG-0006 - Image upload, batch processing, and camera workflow

- Status: `HISTORICAL / IMPLEMENTED`
- Problem/request: example images were shown instead of a real upload/camera flow; stop detection did not work.
- Work recorded: image upload accepts controlled normalized media, supports one to ten images, async task states, cancellation, source/derived media separation, review, and record retrieval. Camera flow uses `getUserMedia`, pauses/resumes with generations, prevents stale frames, stops tracks, and can save a current result.
- Affected areas: `ui/detection.js`, `endpoints/media.py`, `detections.py`, `records.py`, `camera.py`, `services/detection.py`, worker path.
- Verification: historical synthetic-image YOLO subprocess smoke.
- Remaining: hardware permission, device switching, disconnection, and cross-device HTTPS acceptance are open.

### CHG-0007 - Internal communications and group creation

- Status: `HISTORICAL / IMPLEMENTED`
- Problem/request: contacts could not be opened, group creation did not persist or invite members, messages did not send, and the communication view disappeared.
- Cause: earlier UI actions were incomplete and notification behavior could turn a committed write into a failed response. The historical fix records `anyio.from_thread.run` for notification bridging and separates notification failure from persistence result.
- Work recorded: private conversations, admin-created invited groups, public room join acknowledgement, text/Emoji messages, membership checks, group dissolution read-only history, presence, exact string cursor pagination, and safe member-scoped export/search.
- Affected areas: `ui/chat.js`, `ui/chat-history.js`, chat/community endpoints and services.
- Verification: historical isolated group idempotency and browser send/persistence checks.
- Remaining: LAN multi-device deployment and scale behavior are open.

### CHG-0008 - Operational logging and safe diagnostics

- Status: `HISTORICAL / IMPLEMENTED`
- Problem/request: maintenance needed traceable logs without exposing sensitive content.
- Work recorded: request IDs, safe route templates, operation/audit records, browser diagnostic enums, and rotating file logs. Uvicorn access logging is disabled in the documented command to avoid raw query logging.
- Affected areas: `core/logging.py`, `main.py`, `endpoints/system.py`, `client_logs.py`, admin UI.
- Constraint: no passwords, keys, bodies, or chat content in the designed logs.
- Remaining: automated database-log retention and volume governance are open.

### CHG-0009 - Provider configuration, multi-agent assistant, and digital-human page

- Status: `HISTORICAL / IMPLEMENTED`
- Problem/request: LLM configuration, digital-human assistant, and internal communication interfaces were missing or non-responsive.
- Work recorded: provider credentials are stored encrypted; capability tests require explicit consent and use at most one or two fixed text calls; successful test does not auto-enable a provider. Agents have controlled lifecycle/versioning. Assistant requests freeze an exact outbound payload and require a separate confirmation. The avatar module supports a local self-contained GLB path with fallback image and renderer resource checks.
- Affected areas: `ui/admin.js`, `ui/assistant.js`, `ui/avatar.js`, operations/agents/assistant endpoints and LLM services.
- Remaining: real vendor credentials and costs, real structured response acceptance, formal GLB asset, target GPU, and cloud provider acceptance are open.

### CHG-0010 - Assistant evidence, structured output, and citation revocation

- Status: `HISTORICAL / IMPLEMENTED`
- Problem/request: ensure reports do not invent detection facts and that users can inspect authorized sources.
- Work recorded: `customs-text-v3` freezes server-derived detection facts; business modes validate strict JSON; citations map only to authorized records or knowledge chunks; citation retrieval rechecks ownership, source version, state, and content hash; revoked sources hide old results. Tool/function calls from provider output are rejected.
- Affected areas: `services/assistant_output.py`, `services/llm.py`, assistant endpoints, `ui/assistant.js`, `ui/markdown.js`.
- Verification: historical offline tests covering invalid structures, tool-call rejection, citations, and revocation.
- Constraint: this reduces unsupported claims but does not prove the factual correctness of natural-language knowledge explanations.

### CHG-0011 - Documentation baseline and AI handover protocol

- Status: `COMPLETED on 2026-09-07`
- Problem/request: provide a Chinese human README, an English AI development document that captures requirement sources and modification history, and a Chinese human-readable development history so future AI work can understand context first.
- Cause/evidence: repository had `backend/README.md`, implementation notes, and primary requirement files but no root human README, no English AI handover, no Chinese chronological change ledger, and no root maintenance protocol. Git had no commits, so exact historic patches cannot be reconstructed.
- Work performed: added root `readme.md`, `AGENTS.md`, this handbook, and `docs/DEVELOPMENT_HISTORY_ZH.md`; linked primary documents; recorded source hashes, evidence limits, safe operation rules, current implementation map, and a structured historical ledger.
- Affected files: `readme.md`, `AGENTS.md`, `docs/AI_DEVELOPMENT.md`, `docs/DEVELOPMENT_HISTORY_ZH.md`.
- API/data/security effect: documentation only; no runtime code, database, account, key, media, model, or session mutation.
- Verification: 2026-09-07 source-link and ledger-ID checks passed; the English handbook contains ASCII text only; `npm run check` passed. No full business test suite was re-run because this change only adds documentation.
- Rollback: remove only the four documentation files in a future version-control commit; no data rollback is required.

### CHG-0012 - GitHub CLI installation and initial repository publication

- Status: `COMPLETED on 2026-09-07`
- Request/problem: publish the local project to `worldcopyist/Customs-Suspect-Identification-System` after direct Git HTTPS push lacked a usable credential.
- Facts and constraints: the GitHub connector confirmed administrative push permission, but its exposed API did not provide a lossless local-workspace upload primitive for the repository's binary assets. The remote initially contained only commit `31f8015` and a root `LICENSE`. The local repository had no earlier commits.
- Work performed: installed GitHub CLI 2.100.0 for macOS arm64 from the official release after matching the published SHA-256 checksum; configured Git to use the authenticated CLI credential helper; preserved and merged the remote `LICENSE`; pushed the existing merge commit without force.
- Result: `main` advanced from `31f8015` to `a531734d2fdfa6c08d2da9275f45d6990f9a5ee1`. The project commit is `bc9683859eb77edcaca133725061ced8afa5de97`; the merge commit retains the remote initial history.
- Affected files: no runtime source, database, media, model, or secret file was changed by the installation/push. This ledger entry and its Chinese counterpart are the only project-file changes for this record.
- Verification: GitHub CLI reported the authenticated `worldcopyist` account; non-force push completed; GitHub commit query and local `origin/main` both resolved to `a531734d2fdfa6c08d2da9275f45d6990f9a5ee1`.
- Security: no token value is stored in the repository or this document. The local CLI credential is held by the operating-system credential store.
- Rollback: remove a future repository commit only after evaluating collaborators and history; do not force-push or delete the remote branch merely to undo this publication.
- Chinese counterpart: `docs/DEVELOPMENT_HISTORY_ZH.md#chg-0012`

### CHG-0013 - Repository privacy exclusions and publication audit

- Status: `COMPLETED on 2026-09-07`
- Date: 2026-09-07
- Request/problem: stop publishing the user-designated local design, source-document, and archive paths; audit the current publishable tree for personal names, tokens, API credentials, and related private material.
- Requirement references: explicit user request on 2026-09-07; this repository handbook sections 3, 4, and 8.
- Facts, hypotheses, and missing information: `origin/main` and the local `master` head both resolved to `4ba58e3` before this work. The requested paths are currently tracked. Removing them from the index prevents future tree publication but does not erase objects, file names, or contents already present in Git history. History rewrite and force push are out of scope without explicit approval.
- Root cause or reasoned conclusion: `.gitignore` does not affect paths already tracked by Git. Current documentation also linked to a requested-to-exclude source directory, so those links must be replaced by controlled-source references.
- Work performed, in order: added root-anchored ignore rules without personal names; removed 24 requested tracked items from the Git index with `git rm -r --cached` while confirming all local paths remain present; replaced public links to the controlled sources with source-register references; scanned the staged publishable tree and all reachable history for common live credential signatures; checked current PNG metadata fields without exposing metadata values.
- Affected files, routes, data, permissions, and security boundaries: Git tracking rules and maintenance documents only. Local source documents and visual assets must remain on disk. No runtime route, database, account, credential, media, or model mutation is authorized.
- Verification commands and actual results: `git fetch origin main`, remote comparison, and tracked-path inventory showed both heads at `4ba58e3` before work. `git check-ignore --no-index` matched all four requested path classes. The staged deletion count is 24 and the prohibited paths are absent from the current index. `git diff --cached --check` passed. No current-index or reachable-history match was found for the scanned GitHub, OpenAI-style, AWS, Google, Slack, or private-key signatures. The only credential-related source hits are expected configuration placeholders, application security code, documented initial/development credentials, and isolated test credentials; they are not evidence of a deployed secret. Neither retained PNG has Artist, Copyright, GPS, or UserComment EXIF fields. The handbook ASCII check and controlled-source link check passed.
- Rollback or recovery: restore a future tracked-path change with `git restore --staged` before committing, or a later non-force commit after review. Do not delete local source material.
- Remaining risks, external dependencies, and follow-up IDs: this is a pattern-based review, not a forensic or legal privacy certification. Current history still contains the excluded material and its historical paths; a history-rewrite decision requires explicit user authorization and collaborator impact assessment. A public deployment must replace the development application-key placeholder and documented/test passwords with managed secrets; that runtime security change is out of scope here.
- Chinese counterpart: `docs/DEVELOPMENT_HISTORY_ZH.md#chg-0013`

### CHG-0015 - Approved YOLO replacement and pre-login animation preview

- Status: COMPLETED
- Date: 2026-09-08
- Request: deploy the user-supplied `/Users/Admin/Downloads/best.pt` in place of the current local YOLO weights, and present the supplied `animitor.html` and `xuanzhuan.html` as reversible startup animation before the anonymous login page.
- Requirement references: explicit user request on 2026-09-08; controlled PRD AC-05, AC-06 and AC-26; architecture inference-worker boundary; AI-design detection output boundary.
- Observed evidence and compatibility conclusion: the old approved artifact SHA-256 is `6f4a8baed78f970a5141cc43e356af8f68c8cef6e7e73ab376ea6893ed4a2b1a` and exposes `{0: "sus"}`. The supplied artifact SHA-256 is `d8387eb6ed98d6ff13013f8dc5b1eaac87cb243dc9aa8bc931adf2789abe9329`, loads as an Ultralytics `detect` task, and exposes `{0: "handsome"}`. The current strict worker rejects any changed class contract, so replacing only the binary would leave detection unavailable. The supplied HTML files are static but reference five same-directory `image/` assets; the user subsequently supplied that directory. Model loading proves format compatibility only, not accuracy, intended semantics, legal suitability, or real-camera performance.
- Work performed: copied the five user-provided animation images to `assets/startup-animation/` with their recorded source fingerprints; preserved the old model in ignored `backend/models/backups/suspect-yolo11n-best-6f4a8baed78f.pt`; atomically installed the approved new artifact; updated the fixed SHA-256, one-class worker contract, box label rendering and assistant fact wording to `handsome`; added no model web-management API. Adapted the two static user HTML animations to same-origin asset paths and enterprise text, inserted a sandboxed sequence with a skip control before anonymous login, and made the CSP allow only `/ui/intro/` pages to be framed by the same origin. Updated the controlled-source addenda, README and implementation records.
- Verification: direct Ultralytics load confirmed the configured artifact, `detect` task and exact names mapping, and completed a real synthetic-image prediction with zero boxes. The worker readiness hash check passed. `npm run check` passed, including the startup-resource/no-script/no-external-resource test. All 40 isolated backend tests passed with two upstream FastAPI/Starlette deprecation warnings. HTTP checks returned 200 for health, both animation HTML files and representative animation images, and exposed `frame-src 'self'`; browser checks visibly played both stages and then reached the anonymous login page. The first browser attempt failed because global `frame-ancestors 'none'` also blocked the sandboxed child page; the policy was narrowed for the two static intro pages and the browser recheck passed.
- API/data/security effects: no route, schema, migration, account, or threshold change. New detection rows may contain `handsome`; old rows remain `sus`. Animation pages make no API call and are sandboxed; only their static paths use `frame-ancestors 'self'`, while all other responses retain `frame-ancestors 'none'`. Model and backup fingerprints are documented; the backup directory is ignored by Git.
- Remaining work: no accuracy, bias, real-camera, physical-device, legal-source, or production suitability acceptance was performed. A user visual review remains the acceptance decision for the animations; revert only this change if it is not approved.
- Boundaries: no account, database, source-media, provider credential, network bind address, automatic model training, or inference threshold change is authorized. Existing historical detection records retain their old `sus` class snapshots. The new `handsome` label remains a model candidate category, not a person identity, appearance judgment, criminal conclusion, or enforcement decision.
- Rollback plan: restore the checksum-matched local backup and revert only the CHG-0015 source/assets; do not delete records created while the new model is active merely to roll back the executable artifact. Chinese counterpart: `docs/DEVELOPMENT_HISTORY_ZH.md#chg-0015`.

### CHG-0016 - Publish current work and remove private paths from remote history

- Status: COMPLETED on 2026-09-08
- Request/problem: the user asked to upload the project to its GitHub repository, including only the files that are required to be uploaded. The user then explicitly authorized rewriting the published history and force-pushing so the CHG-0013 excluded paths (design screenshots, page materials, and the day4_1 source-document archive) no longer appear in any reachable commit.
- Requirement references: explicit user requests on 2026-09-08; this handbook sections 3, 8 (CHG-0013 remaining risk), and the AGENTS.md force-push authority rule (satisfied by the direct user decision recorded in this session).
- Facts, hypotheses, and missing information: before this work, local `master` and `origin/main` both resolved to `4ba58e3`. The working tree carried CHG-0014/CHG-0015 code, the approved model replacement, animation assets, staged CHG-0013 index removals, and eight previously untracked runtime files (theme, intro, check scripts, startup images). The five startup-animation images are referenced by the served `/ui/intro/` pages and are therefore required for the application to work; they are not among the user-excluded private paths. CHG-0013 had missed a 21 MB archive whose percent-encoded path is `%E5%89%8D%E7%AB%AF%E9%A1%B5%E9%9D%A2%E6%95%88%E6%9E%9C%E5%9B%BE-18%E5%BC%A0PNG.zip` (the design-screenshot folder name plus `-18 PNG` and a `.zip` suffix) that was tracked from the first project commit; this entry supersedes the CHG-0013 statement that all 24 requested items were the complete exclusion set.
- Root cause or reasoned conclusion: CHG-0013 removed the private paths only from the index, so earlier published history still exposed them on GitHub. A history rewrite plus non-fast-forward update is the only in-repository way to remove them from the public view. The zip miss happened because default Git output octal-escapes non-ASCII paths, so a plain-text grep for the Chinese directory names did not match it; verification was redone with `core.quotePath=false`.
- Work performed, in order: staged and committed all publishable changes (13 additions, 27 modifications, 24 index removals; credential-signature scan of the staged diff found no live secrets; `npm run check` passed with five PASS lines); created a full `git bundle` backup at `~/suspect-repo-backup-before-rewrite-20260908.bundle`; installed git-filter-repo from the upstream single-file script; rewrote all commits twice with `--invert-paths` to drop the `day4_1_*` paths, the two excluded Chinese directories, and the missed zip; re-added the `origin` remote that filter-repo removes by design; force-pushed `master` to remote `main` twice with `--force-with-lease` pinned to the observed remote value.
- Affected files, routes, data, permissions, and security boundaries: version-control history and the local repository only. No runtime route, database, account, credential, media, or model mutation. Local copies of the excluded private paths remain on disk and stay ignored.
- Verification commands and actual results: after each rewrite, `git rev-list --all` with per-commit `git ls-tree -r` (quotePath disabled) reported zero matches for the excluded-path pattern (`day4_1_*`, the two percent-encoded Chinese directory names, and any `.zip` archive). The rewritten `HEAD` tree contains 127 files including `LICENSE`, theme/intro modules, and the model blob whose SHA-256 still matches the CHG-0015 approved value `d8387eb6...9329`. `gh api .../git/trees/<sha>?recursive=1` for every reachable remote commit returned zero private-path matches; the remote `main` head is the final rewritten commit and the previous leaked head is no longer reachable from `main`.
- Rollback or recovery: `git bundle verify` passed for the pre-rewrite backup; cloning it restores the original history if needed. Removed public objects may linger in GitHub caches or fork networks until GitHub support cleanup is requested; that residual risk was explained to and accepted by the user.
- Remaining risks, external dependencies, and follow-up IDs: force-push changed every commit ID after `351595b`; any other clone of the old history must re-clone or hard-reset. GitHub cached views of removed content may persist briefly.
- Chinese counterpart: `docs/DEVELOPMENT_HISTORY_ZH.md#chg-0016`

<a id="chg-0017"></a>
### CHG-0017 - V1.3 functional contract revision, documentation only

- Status: COMPLETED on 2026-09-08 (documentation only)
- Date: 2026-09-08
- Request/problem: update project documents only for the task brief and the user's explicit scope: JWT, model discovery/autofill, speech and multimodal providers, manager-controlled avatar replacement, aligned database/results paths, and remaining functional gaps. Submission materials and acceptance-evidence work are excluded.
- Requirement references: explicit user request on 2026-09-08; supplied task brief functional sections on pages 1-5; controlled PRD, API, architecture and AI design, with CHG-0014/CHG-0015 addenda.
- Facts and cause: current code uses opaque sessions, text-only assistant/chat, deployment-only GLB, backend/data and backend/media. Supplied avatar files are PMX 2.0 with textures and noncommercial/no-redistribution notices, not ready-to-load GLB. The approved model is handsome, but ui/detection.js still hardcodes sus for camera labels, correcting the completeness claim in CHG-0015.
- Ordered work: read handbooks and current callers/routes/schemas/storage; match all four baseline fingerprints; inspect supplied asset headers and notices without executing embedded content; check official vendor catalog, Qwen-Omni and JWT documentation; add leading authoritative V1.3 sections with explicit historical supersession to all four designs; align native frontend, API/data/security boundaries, README and status records; check links, tables, identifiers and updated fingerprints.
- Affected files and effects: four controlled design documents, readme.md, backend/README.md and four maintenance documents. Future API/data/security changes are specifications only; no runtime, account, database, secret, asset, Git publication or cloud inference mutation is authorized in this turn.
- Verification: initial document checker found two unescaped table separators in new API rows; both were corrected. Initial source inspection used one nonexistent backend/app/web/ui path, then resolved the real ui/detection.js caller. The first DeepSeek documentation fetch timed out and a guessed Qwen catalog URL failed; official search resolved the documented catalog pages, which are the final citations. Final checker passed: 10 associated documents, 27 local links, 17 matching ledger IDs, four updated controlled-source hashes, no table/fence/anchor issue, English handbook ASCII, documentation-only changed paths, and git diff --check. No business tests, cloud inference or acceptance work was run.
- Rollback: controlled backup /tmp/customs-docs-v13.3NnOip/before-contract-edit.tar contains the ten documents before contract edits, with the new IN_PROGRESS ledger already present. Restore only intended design/prose edits and add a later correction record; do not erase historical ledger entries or restore runtime data. The backup includes private source material and must not be published.
- Remaining: implementation remains pending; asset activation is conditional on format preparation and permitted use. No commercial or redistribution permission is inferred.
- Chinese counterpart: [CHG-0017](DEVELOPMENT_HISTORY_ZH.md#chg-0017).

### CHG-0014 - Theme selection and enterprise demo branding

- Status: COMPLETED
- Date: 2026-09-07
- Request: light, dark and live system-following themes; replace educational branding with enterprise demo presentation.
- Evidence: frontend.css hardcodes dark workspace and light authentication colors; UI and backend-generated text still carry educational labels.
- Plan: initialize persistent browser theme before rendering, add a global selector, update product text and future generated watermarks, then verify isolated tests and browser behavior.
- Boundaries: preserve database paths, existing media, credentials and historical ledger entries. This explicit request supersedes earlier educational branding; human review and identity limitations remain.
- Work performed: added ui/theme.js before stylesheet loading and ui/theme.css for both appearances; global accessible select defaults to system, persists locally and synchronizes tabs. Updated UI, legacy mockup text, backend API title, assistant messages and future watermarks. Updated README, backend README, original controlled source addenda and hashes. Historical migration content, stored custom prompts, media and database identifiers remain unchanged.
- Affected files: index.html, ui/theme.js, ui/theme.css, ui/core.js, ui/admin.js, ui/assistant.js, ui/detection.js, app.js, app-live.js, backend/app title and text-generation modules, scripts/check-theme.mjs, package.json and maintenance documents.
- API/data effects: no new API or schema. Browser preference is device-local, not account-wide. Newly generated reports and images use enterprise wording; existing outputs remain historical artifacts.
- Verification: 40 isolated backend tests passed (two dependency deprecation warnings); npm run check and theme event tests passed. Browser confirmed login/register theme selection, dark refresh persistence and computed light/dark panel colors. System-change and denied-storage paths were verified with an isolated event harness, not by changing the host OS. Authenticated workspace visual acceptance remains for user testing. Local service restarted on loopback with current code; health and static theme resources checked.
- Rollback: revert only CHG-0014 edits; no data restoration needed. Chinese counterpart: docs/DEVELOPMENT_HISTORY_ZH.md.


## 9. Open work register

Historical acceptance items below are retained for continuity, not added to the current user's documentation-only scope. CHG-0017 creates target contracts; future implementation needs a separate change entry.

<a id="chg-0018"></a>
### CHG-0018 - Migrate selected fixes from user-supplied modified archive

- Status: COMPLETED
- Date: 2026-09-08
- Request/problem: inspect the user-supplied Customs-Suspect-Identification-System-main.zip, migrate its applicable modifications into this original workspace, and summarize all archive changes.
- Requirement references: explicit user request on 2026-09-08; AGENTS.md read-before-change and change-ledger rules; current session/authentication, LLM and cross-platform startup boundaries.
- Facts, hypotheses, and exclusions: archive SHA-256 is 6cb3ae84eb91f3d3a86554b8114bbe258308d02e326d53929df7e76ec99ff4dc. It contains 227 entries including a SQLite database, application log and Python bytecode caches, which are generated/private runtime state rather than source changes. Source comparison found changed auth, middleware, LLM, admin UI, core UI, SQLite baseline, documentation and a new Windows start script. The archive has no primary controlled V1.3 documents. Its docs are older than the current CHG-0017 revisions.
- Reasoned selection: evaluate each source difference against current contracts. Candidate fixes are logout response handling, middleware null-status resilience, Qwen thinking control, and a Windows launcher. Do not blindly migrate the SQLite minimum-version downgrade, removal of visible request IDs, generated state, or older docs. The archive middleware fix itself leaves later raw status comparisons, so correct the full path rather than copying a partial change.
- Work performed, in order: compared source rather than executing archive content; changed logout to retain its declared 204 empty response while clearing the session cookie; made all request-log and audit comparisons use a safe derived status code; added `enable_thinking: false` to non-streaming `qwen3*` payloads to match the established streaming path; added `backend/start.bat`, which prefers the local virtual environment and invokes `app.main` on loopback; added isolated regressions for logout and the Qwen payload. The first test insertion interrupted a predecessor test cleanup block; static inspection exposed the dangling indentation and it was corrected before test execution.
- Affected files/effects: auth, middleware, LLM payload, isolated tests, Windows local launcher and operational documentation. No route, role, data schema, SQLite baseline, archive database, log, cache, model, credential, account, source media or controlled design document was imported or changed.
- Verification: targeted auth/health tests passed 5 tests with 2 upstream dependency deprecation warnings. Full final suite passed 42 tests with 2 such warnings; frontend `npm run check` passed all 5 checks; Python compilation and `git diff --check` passed. Tests used isolated databases. No cloud request, production-database mutation, service publication or Windows runtime test was performed; the launcher received static review only.
- Rollback: revert only selected CHG-0018 files; remove a newly added launcher if needed. Do not restore archive runtime database/log/cache files.
- Chinese counterpart: [CHG-0018](DEVELOPMENT_HISTORY_ZH.md#chg-0018).

<a id="chg-0019"></a>
### CHG-0019 - Implement V1.3 foundation and repair identified runtime gaps

- Status: COMPLETED (partial V1.3 foundation)
- Date: 2026-09-08
- Request/problem: implement the revised project documents, add missing functionality, repair known defects, and replace the authentication method.
- Requirement references: PRD V13-01 through V13-08; API C13-00 through C13-09; architecture A13-01 through A13-09; AI design AI13-01 through AI13-10; explicit user request on 2026-09-08.
- Facts and scope control: current code remains V1.2 with opaque cookie sessions, `backend/data` and `backend/media`, text-only assistant flows, and a GLB deployment reader. The target is a breaking JWT/data-root/multimodal/asset-management contract. It cannot be safely fulfilled by recreating an existing database or by copying the unlicensed PMX source into the repository. Work starts with inspectable migration-compatible foundations and existing defects; cloud calls, asset activation and production-data migration remain excluded unless separately safe and testable.
- Work performed, in order: added migration 20260908_0007 with User/AuthSession auth-version fields and revocation of all legacy opaque sessions; replaced the V1.2 identity cookie with a locally signed HS256 JWT in HttpOnly customs_access, using a distinct signing key and claims for issuer, audience, sub, sid, jti, times, auth version and phase; kept every request and WebSocket subject to current session, user state and auth-version validation; made successful new login revoke older account sessions; made password, role, permission, status, delete and reset changes increment auth version and revoke old sessions; separated anonymous CSRF context from the access JWT; cleared stale/revoked browser tokens before a re-login; changed default paths to database/ and results/, added an explicit initializer, and prevented normal startup from seeding a missing database; repaired camera output to render returned class_name rather than hardcoded sus.
- Deferred scope: model catalog/discovery and form autofill, VISION/ASR/TTS/OMNI, screenshot chat attachments, avatar asset lifecycle/PMX conversion, detect_log physical migration, and actual old-root data/media migration remain unimplemented. They require separate data models, provider protocol adapters, controlled conversion, license confirmation, and a maintenance window. No placeholder route claims these abilities work.
- Verification: targeted auth suite passed 3 tests; full backend suite passed 43 tests with 2 upstream dependency deprecation warnings; frontend npm run check passed 5 checks; changed Python files compiled and git diff --check passed. Tests used isolated SQLite/media roots. No cloud provider, camera hardware, PMX asset, production database, LAN service, or Windows runtime was used.
- Security/data boundaries: no password reset, existing encryption-key rotation, service publication, paid provider call, PMX import, or production data migration was performed. Old browser sessions are intentionally revoked by the migration; accounts, password hashes, provider secrets and business records are preserved.
- Rollback: restore a verified database backup for the non-downgradable authentication migration, then revert only the listed application/config/UI/docs changes. Do not restore V1.2 browser tokens or copy archive/runtime data over the current database.
- Chinese counterpart: [CHG-0019](DEVELOPMENT_HISTORY_ZH.md#chg-0019).

| ID | Status | Work | Required evidence before closure |
| --- | --- | --- | --- |
| OPEN-001 | SUPERSEDED by CHG-0017 | V1.3 architecture retains native ES modules | Documentation alignment only; no framework migration was performed |
| OPEN-002 | OPEN | Real cloud provider and structured output acceptance | User-approved credentials/budget, isolated evidence, no secret disclosure |
| OPEN-003 | OPEN | Formal self-contained GLB and GPU acceptance | Licensed asset, budget validation, renderer/fallback tests on target device |
| OPEN-004 | OPEN | Physical camera and LAN HTTPS acceptance | Permission, disconnect/reconnect, device switch, trusted HTTPS, multi-device tests |
| OPEN-005 | OPEN | Log retention and capacity governance | Retention policy, safe cleanup plan, backup/restore test, volume monitoring |
| OPEN-006 | OPEN | Concurrency, restart, fault, Windows, and long-run testing | Defined scenarios and dated results |
| OPEN-007 | OPEN | Provider test global quota/concurrency hardening and DNS connection pinning | Threat model and concurrency/security tests |
| OPEN-008 | OPEN | Assistant source/history pagination and UI edge cases | UX decision and integration tests |
| OPEN-009 | PLANNED, NOT IMPLEMENTED | V1.3 JWT, model discovery, multimodal/speech, avatar management, storage migration and functional gaps | Explicit implementation work after this documentation-only change |

## 10. Entry template for future changes

```markdown
### CHG-NNNN - Short title

- Status: IN_PROGRESS | COMPLETED | BLOCKED | SUPERSEDED
- Date: YYYY-MM-DD
- Request/problem:
- Requirement references:
- Facts, hypotheses, and missing information:
- Root cause or reasoned conclusion:
- Work performed, in order:
- Affected files, routes, data, permissions, and security boundaries:
- Verification commands and actual results:
- Rollback or recovery:
- Remaining risks, external dependencies, and follow-up IDs:
- Chinese counterpart: `docs/DEVELOPMENT_HISTORY_ZH.md#chg-nnnn`
```

Do not edit an earlier ledger entry to erase a contradiction. Add a later correction or supersession entry that names the older ID.
