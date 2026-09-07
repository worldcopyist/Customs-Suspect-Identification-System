# AI Development Handbook

## 1. Purpose and scope

This is the English handover document for AI-assisted maintenance of the Customs Suspect Identification System. Read this file before planning, reviewing, changing, testing, or deploying the repository. It is a development aid, not a replacement for the Chinese source requirements.

The project has no Git commit history at the time of this document. The earlier ledger below is a reconstruction from available source files, local implementation notes, test evidence, and user-reported issues. It cannot recover every historical line edit, precise timestamp, or unrecorded failed attempt. Do not present a reconstructed item as a complete audit trail.

Facts are marked as `OBSERVED` when they were checked in source, tests, runtime, or dated records. `HISTORICAL` means a prior work record exists but was not re-run for this documentation change. `OPEN` is an unverified, deferred, or external dependency. Requirement documents describe target behavior; they do not prove implementation.

## 2. Mandatory reading order

1. Read `AGENTS.md`, this document, `docs/DEVELOPMENT_HISTORY_ZH.md`, and `readme.md`.
2. Read the relevant primary requirement sections listed in the source register.
3. Inspect current frontend callers, API routes, schemas, permission checks, persistence, migrations, and tests.
4. Compare requirements, implementation, and evidence. State conflicts before changing behavior.
5. Add a new `CHG-NNNN` ledger entry in this file and the Chinese history before implementation. Update both after verification.

Never rely only on screenshots, a health endpoint, a historical note, an unmounted legacy file, or a passing unit test to claim end-to-end behavior.

## 3. Source register

| Source | Role | Version/date | Integrity snapshot on 2026-09-07 |
| --- | --- | --- | --- |
| [Product Requirements Document](../day4_1_%23fcosbrk_%E5%88%98%E7%9D%BF_%E6%96%87%E6%A1%A3/PRD.md) | Product scope, roles, acceptance criteria | V1.2, 2026-09-05 | SHA-256 `ce2ae7e3c9726ef12d96ea3e37bfa6173c26a874b8333d6856f892273501d10e` |
| [API Contract](../day4_1_%23fcosbrk_%E5%88%98%E7%9D%BF_%E6%96%87%E6%A1%A3/%E6%8E%A5%E5%8F%A3%E6%96%87%E6%A1%A3.md) | REST, WebSocket, error, state, and permission contract | 1.1, 2026-09-05 | SHA-256 `06dfb372201f9c04dbe2b72fa5b93a23bcbbce03d5f4fd6a16a67ef82809bf31` |
| [Architecture Design](../day4_1_%23fcosbrk_%E5%88%98%E7%9D%BF_%E6%96%87%E6%A1%A3/%E6%8A%80%E6%9C%AF%E6%9E%B6%E6%9E%84%E6%96%B9%E6%A1%88.md) | Intended architecture and deployment constraints | 1.1, 2026-09-05 | SHA-256 `2291a49f4338752b141bf3b8660e11a597875fae65f55f1e14dfa892941c96a8` |
| [AI Technical Design](../day4_1_%23fcosbrk_%E5%88%98%E7%9D%BF_%E6%96%87%E6%A1%A3/AI%E6%8A%80%E6%9C%AF%E6%96%B9%E6%A1%88.md) | Detection, cloud text, safety, and avatar boundaries | 1.1, 2026-09-05 | SHA-256 `3e0bec04f8de6c63dd8ec735f178e270badc4a49618b4e3ff297fcffe22ff390` |
| `docs/V1.2_IMPLEMENTATION.md` | Dated implementation and verification record | updated 2026-09-07 | Current status, not a requirements replacement |
| `docs/IMPLEMENTATION_BOUNDARIES.md` | Module-to-source map and implementation limits | updated 2026-09-07 | Current status, not a requirements replacement |
| `backend/README.md` | Runtime, backup, dependency, and safety operations | V1.2 | Operational instructions |

If any primary file changes, update the date and SHA-256 here and re-evaluate entries that depend on it.

## 4. Non-negotiable system boundaries

- The local YOLO model returns only `sus` candidate boxes. It does not identify a person, estimate criminal probability, deduplicate people, track across cameras, or make an enforcement decision.
- Person links are manual, permission-checked associations. A retained review is not a confirmed identity or a legal conclusion.
- Do not send images, camera frames, or internal chat content to a cloud model. Cloud text requires an exact prepared preview and explicit confirmation.
- Do not add arbitrary model upload, web-managed YOLO weights, threshold edits, automatic vendor fallback, automatic cloud retries, speech, chat attachments, full private-chat audit, or external-network messaging unless requirements are explicitly changed first.
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

- Frontend: native JavaScript ES modules. The architecture design specifies Vue 3, Vite, Vue Router, Pinia, and Element Plus, but those are **not** the current implementation. Do not claim architecture parity.
- Backend: Python/FastAPI/SQLAlchemy/Alembic with SQLite. Migrations are in `backend/migrations/versions/` through `20260905_0006_v12.py`.
- Frontend entry is `index.html` -> `frontend.js` -> `ui/core.js`, `ui/detection.js`, `ui/chat.js`, `ui/assistant.js`, and `ui/admin.js`. Legacy `app.js`, `app-live.js`, and style files remain on disk but are not the served entry path.
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
5. Avatar: only a deployer-reviewed self-contained GLB is allowed for the 3D path. The present adult-male raster placeholder is not a formal 3D delivery.
6. AI: structured output and citations reduce unsupported claims but do not prove natural-language accuracy. Human review remains required.
7. Architecture: implementation extensions and deviations must be documented. Native ES modules are a material current deviation from the Vue/Vite target.

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

## 9. Open work register

| ID | Status | Work | Required evidence before closure |
| --- | --- | --- | --- |
| OPEN-001 | OPEN | Vue 3/Vite migration or explicit architecture revision | Approved plan, route/state/component migration, regression tests |
| OPEN-002 | OPEN | Real cloud provider and structured output acceptance | User-approved credentials/budget, isolated evidence, no secret disclosure |
| OPEN-003 | OPEN | Formal self-contained GLB and GPU acceptance | Licensed asset, budget validation, renderer/fallback tests on target device |
| OPEN-004 | OPEN | Physical camera and LAN HTTPS acceptance | Permission, disconnect/reconnect, device switch, trusted HTTPS, multi-device tests |
| OPEN-005 | OPEN | Log retention and capacity governance | Retention policy, safe cleanup plan, backup/restore test, volume monitoring |
| OPEN-006 | OPEN | Concurrency, restart, fault, Windows, and long-run testing | Defined scenarios and dated results |
| OPEN-007 | OPEN | Provider test global quota/concurrency hardening and DNS connection pinning | Threat model and concurrency/security tests |
| OPEN-008 | OPEN | Assistant source/history pagination and UI edge cases | UX decision and integration tests |

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
