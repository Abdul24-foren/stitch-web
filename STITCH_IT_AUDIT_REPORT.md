# STITCH IT Production-Readiness Audit

**Audit date:** 2026-11-12  
**Assessment:** Not production-ready; suitable as a local MVP foundation after configuring a real session secret.

## 1. Scope and approach

Inspected the tracked application, templates, CSS/JavaScript, configuration, dependency manifests, tests, and project documentation. The repository contains no other application modules or AI measurement scripts. The virtual environment was excluded from the feature inventory. The local `.env` values were not reported or changed. The existing SQLite database was opened read-only for schema and row counts; its contents were not modified.

The existing database contains the six ORM tables (`users`, `tailor_profiles`, `designs`, `measurements`, `orders`, `deliveries`), four seeded designs, and zero user, measurement, order, or delivery rows.

## 2. Architecture discovered

- **Backend:** synchronous FastAPI route handlers, FastAPI forms and file uploads, Starlette signed-cookie sessions.
- **Views/frontend:** Jinja2 server-rendered HTML, plain CSS and a small vanilla JavaScript form-submit enhancement. No SPA framework, Node package manifest, frontend build, or frontend test runner.
- **Persistence:** SQLAlchemy ORM with SQLite by default; `Base.metadata.create_all()` initializes tables and a service seeds designs. There is no migration framework.
- **Models:** original user, tailor, design, measurement, order, and delivery models, plus address, business/service, delivery availability, private reference image, order details/snapshots/idempotency, status-history, and notification models. Statuses remain strings and prices/measurements use floating-point columns.
- **Files:** bounded local `uploads/` storage for private order reference images; no managed object-storage integration.
- **AI, payment, messaging:** no camera processing, pose/landmark/SMPL-X pipeline, Razorpay client, webhook, email/SMS service, notification queue, or background task was present.
- **Browser/API routes:** server-rendered account, dashboard, profile/address/measurement, tailor discovery, order, notification, delivery, and reference-image routes, plus `/health` and `/designs`.

## 3. Feature status matrix

Status definitions: **IMPLEMENTED** means the core workflow exists and was exercised; **PARTIALLY IMPLEMENTED** means a limited workflow exists but one or more requested parts are missing; **NOT IMPLEMENTED** means no corresponding functional integration exists; **BROKEN** means the existing behavior failed verification; **NOT APPLICABLE** means no such feature is present in this architecture.

| Area | Feature | Status | Evidence / limitation |
|---|---|---|---|
| Customer | Registration, login, logout | PARTIALLY IMPLEMENTED | Password hashing, basic validation, and session login/logout work. No email verification, password reset, or login throttling. |
| Customer | Role permissions | IMPLEMENTED | Customer, tailor, and delivery endpoints are role- and ownership-scoped; account roles are self-selected and are not business-verified. |
| Customer | Profile and addresses | IMPLEMENTED | Customer profile and owned address add/default/delete flows persist. |
| Customer | Tailor discovery/search/filters | IMPLEMENTED | Public directory supports name/location and service-category search, availability filter, and studio detail pages. Geographic distance search is not implemented. |
| Customer | Design catalogue | PARTIALLY IMPLEMENTED | Seeded text-based blouse designs and JSON endpoint exist. No catalogue administration or design image library. |
| Customer | Image upload | PARTIALLY IMPLEMENTED | Bounded image validation and private order attachment/access exist. Storage is local, not a production object-storage service. |
| Customer | Fabric preferences / stitching instructions | IMPLEMENTED | Order form captures garment, fabric, and instruction details in order snapshots. |
| Customer | Measurement profiles/history/reuse | PARTIALLY IMPLEMENTED | Manual profiles are validated, editable, reusable, and owner-visible; orders can also store a broader set of manual values. No automated measurement history analysis. |
| Customer | AI measurement | NOT IMPLEMENTED | No AI measurement engine or computed outputs. UI and upload response disclose that AI measurement is not performed. |
| Customer | Order creation/history/status | IMPLEMENTED | Requires owned address; includes server-side price calculation and immutable address/measurement/price snapshots, idempotency, history/detail, cancel-before-acceptance, repeat, and receipt confirmation. |
| Customer | Ratings, reviews, feedback | NOT IMPLEMENTED | No review or feedback model, route, or UI. |
| Customer | Payments | NOT IMPLEMENTED | No payment provider integration or payment persistence. |
| Tailor | Registration/login and shop profile | PARTIALLY IMPLEMENTED | Shop/business details, services, hours, pricing, and availability can be managed. No business verification or earnings accounting. |
| Tailor | Incoming orders and decisions | IMPLEMENTED | Assigned tailor can accept/reject pending orders; decisions persist. |
| Tailor | Stitching workflow | IMPLEMENTED | Accept/reject and cutting, stitching, quality-check/rework, and ready-for-pickup transitions persist with history. No customer chat. |
| Tailor | Measurement/design/instructions visibility | IMPLEMENTED | Assigned tailor can see order-specific snapshots, design, instructions, and authorized reference images. |
| Tailor | Earnings, analytics, walk-ins, order history | NOT IMPLEMENTED | No earnings, analytics, walk-in customer, or dedicated reporting feature. |
| Delivery | Registration/login and role access | IMPLEMENTED | Delivery role can access its dashboard; cross-role access is denied. |
| Delivery | Assignment claim and status | IMPLEMENTED | Only ready, unassigned jobs are listed/claimable. Claim is an atomic conditional update; owner-only pickup/delivery status changes were tested. |
| Delivery | Pickup/destination/confirmation/history/earnings | PARTIALLY IMPLEMENTED | Owned assignments, customer destination snapshot, pickup/delivery transitions, and history exist. No earnings accounting or external delivery integration. |
| Notifications | Order and delivery notifications | PARTIALLY IMPLEMENTED | In-app notifications persist for supported events. No email/SMS/push provider. |
| Backend/data | Database persistence and relationships | PARTIALLY IMPLEMENTED | New records persist, SQLite foreign keys are enabled, and duplicate order submissions are idempotent. No migration framework or database check constraints for workflow enums. |
| UI | Responsive server-rendered pages | PARTIALLY IMPLEMENTED | Responsive CSS and role pages exist. This implementation pass did not run browser/device checks or an automated accessibility audit. |

## 4. Working features and verification evidence

Automated tests use temporary SQLite databases and do not write to the existing `stitch_it.db`.

- `tests/test_security.py`: password hashing round trip and rejection of incorrect password.
- `tests/test_workflows.py`: registration, role authorization, logout/login, short-password rejection, measurement validation/ownership, address ownership, tailor discovery, duplicate-order idempotency, order snapshots, tailor decisions/statuses, delivery assignment/status ownership, unauthorized order access, upload validation, status history, notifications, and SQLite foreign-key enforcement.
- **Result:** `9 passed` (`python -m pytest -q`). One Starlette multipart deprecation warning remains.
- **Other checks:** `python -m compileall -q app tests`, `python -m pip check`, and `git diff --check` passed; missing/placeholder session secret was verified to fail closed in the original audit.
- **HTTP smoke test:** isolated app `/health` returned HTTP 200 using a temporary SQLite database.
- **Browser inspection:** homepage and tailor directory were opened at 1440px, 768px, and 375px widths; no horizontal overflow was measured. Role-dashboard visual review, full browser console monitoring, and accessibility automation were not completed.
- **Coverage:** no coverage tool/configuration was present; coverage percentage was not measured.

## 5. Bugs found and fixes applied

1. **Public fallback session key / ignored `.env`:** the app used a known fallback key and did not load the documented `.env`. Configuration now loads `.env`, rejects missing, short, or common placeholder keys, and supports `SESSION_HTTPS_ONLY`; `.env.example` no longer advertises a key value. The existing `.env` was not edited. Generate and set a unique key before running the app.
2. **SQLite foreign keys not enforced:** ORM foreign keys existed, but SQLite defaults to enforcement off. A connection hook now enables `PRAGMA foreign_keys=ON`; the workflow test checks the pragma.
3. **Marketplace workflow gaps:** customer addresses, manual order measurements, service/directory management, order-detail snapshots, order history actions, and in-app notifications are now connected through database-backed routes.
4. **Duplicate order submissions:** order submissions now persist a customer-scoped unique idempotency key and return the existing order when the same key is retried.
5. **Delivery availability and concurrent claiming:** dashboard lists eligible ready orders or the current partner's assignments. Claim uses a conditional database update so two partners cannot both claim the same available record.
6. **Non-finite measurements/prices and empty profiles:** NaN/infinite values could bypass ordinary range comparisons; measurements also allowed an empty profile. Values are now finite/range-checked and at least one measurement is required.
7. **Registration email validation depended on DNS deliverability:** account creation could reject syntactically valid emails because the validator attempted live deliverability lookup. Registration now validates syntax only; this does not verify ownership or deliverability.
8. **Upload memory limit applied after reading the complete file:** upload reads are now bounded at configured maximum plus one byte; over-limit, wrong-MIME, and invalid-image cases are tested.
9. **Startup/timestamp deprecations and input bounds:** startup seeding uses FastAPI lifespan and UTC timestamps; account, phone, notes, and measurement inputs are bounded.

## 6. Security findings and remediation

The delegated security review identified one high-severity issue. It was remediated as described below.

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|----------|------|-------|---------------|------------|
| 1 | 🟠 HIGH | `app/config.py`; `app/main.py` | 9-16; 39-43 | A public fallback session key allowed forged role-bearing cookies when no deployment key was supplied. Replaced with fail-closed key configuration and a configurable HTTPS-only cookie flag. | 9/10 |

Remaining security hardening before production:

- Set `SESSION_HTTPS_ONLY=true` behind HTTPS; the development sample remains HTTP-compatible.
- CSRF validation is now enforced on state-changing browser forms. Add login throttling/rate limiting, password reset, email verification, audit logging, and operational security monitoring.
- Protect customer-upload lifecycle with private managed storage, retention/deletion rules, and access/consent policy before collecting real body images.
- Add an approval/verification process for tailor and delivery accounts if those roles must represent trusted businesses.
- Do not accept real payments until server-side provider order creation, signature verification, webhooks, idempotency, and reconciliation exist.

No payment or notification integration was present to validate.

## 7. UI/UX findings

Branding and the restrained typography/color system were preserved. The public home page and tailor directory expose studios; customers can search/filter, inspect studio pages, and use role-specific workflow forms. Responsive CSS, focus states, and mobile layouts are present. This implementation pass did not run browser/device checks or automated WCAG validation.

Still needed: accessible focus/contrast review, automated WCAG checks, table/list empty and error-state review across real data, real tailor search/filtering, order-reference image UI, customer address and delivery details, and visual regression coverage. No unsupported button or fabricated AI/payment success flow was added.

## 8. Database and API findings

- Initial read-only inspection found four catalogue rows and no users/orders/measurements/deliveries. The local database was not reset or migrated during this follow-up.
- SQLite declared foreign keys are now enforced for new connections without changing or migrating the existing database.
- `create_all()` creates missing tables but does not migrate changed schemas. Production schema evolution needs an explicit migration strategy before model changes.
- Order price is calculated server-side from tailor and design prices. The monetary column is `Float`; use fixed-precision decimal/integer minor units before production billing.
- Status values are strings without database check constraints; transitions are route-validated but not represented by a formal workflow service or audit history.
- Order submission keys are unique per customer and persisted to prevent duplicate creation on retry.
- Address, notification, order-detail, and workflow-history records now exist. No payment, review, or AI-derived measurement records are implemented.

## 9. AI measurement validation

No `fit_body.py`, `measure_blouse.py`, `measure_blouse_linear.py`, `measure_armhole.py`, MediaPipe/OpenCV/SMPL-X dependency, pose detector, landmark pipeline, 3D fitting implementation, or measurement-extraction service was present. The implemented manual fields are bust, waist, shoulder, and armhole, labelled in centimetres. Their persistence, finite/range validation, ownership, order reuse, and tailor display were tested.

There are **no AI-derived measurements and no accuracy results**. Camera access, front/side/back processing, body landmarks, blouse-specific length/sleeve/neck calculations, manual AI corrections, and measurement confidence are not implemented. Do not market or use this application as an AI measurement system until a real engine is integrated and validated against tape-measured ground truth.

## 10. Tests, builds, and dependency checks

| Check | Result |
|---|---|
| `python -m pytest -q` | 8 passed; 1 Starlette/httpx deprecation warning |
| Python compile check (`compileall`) | Passed |
| `python -m pip check` | Passed; no broken requirements |
| Frontend production build | Not applicable; no frontend build system |
| Type checking / linting | No project configuration or tool present |
| Coverage | Not measured |
| Existing database migration | Not run; no migration framework, and no schema migration was needed |

`requirements-dev.txt` now lists pytest and the HTTP test client. The runtime dependencies include `python-dotenv` for documented `.env` loading.

## 11. Changed files

- `app/config.py`, `.env.example`, `requirements.txt`: secure secret configuration and HTTPS-only cookie option.
- `app/database.py`: SQLite foreign-key enforcement.
- `app/main.py`, `app/models.py`, `app/services.py`: database-backed customer/tailor/delivery workflows, role/ownership guards, order idempotency, histories, notifications, and private order references.
- `app/templates/`, `app/static/`: role dashboards, tailor directory/detail and order-detail views, responsive styling and form behavior.
- `tests/conftest.py`, `tests/test_workflows.py`, `requirements-dev.txt`: isolated CSRF-aware integration tests for critical supported workflows.
- `README.md`, `CORE_MARKETPLACE_IMPLEMENTATION_REPORT.md`: setup, implemented behavior, test results, and remaining limitations.

The existing `.env`, SQLite database, and pre-existing untracked `.vscode/` directory were not modified.

## 12. Remaining blockers and production-readiness assessment

**Not production-ready.** The app now supports more core marketplace workflows but remains a local MVP. Before production, configure a unique secret, HTTPS-only cookies, rate limiting, account verification, formal migrations, fixed-precision money arithmetic, and monitored private file storage. AI measurement, payments, reviews, and external notifications/delivery integrations remain absent and must not be represented as working.