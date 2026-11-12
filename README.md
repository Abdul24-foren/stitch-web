# Stitch It — Full-Python MVP

**Measure Right. Stitch Smart. Deliver Perfect.**

A runnable starter marketplace built with **Python FastAPI + Jinja2 + SQLite + HTML/CSS/JavaScript**. It provides one website with separate customer, tailor and delivery-partner role portals.

> This is a functional MVP foundation, not a production-certified tailoring or measurement system. AI measurements, live payment collection, email/SMS, and production delivery integrations require additional implementation, credentials and real-world validation.

## Features included

- Customer, tailor and delivery-partner registration/login.
- Secure password hashing (PBKDF2-HMAC-SHA256) and signed session cookies.
- Role-protected dashboards, server-side authorization, and CSRF protection for state-changing forms.
- Customer profile, multiple saved delivery addresses, and reusable manual measurement profiles.
- Tailor directory with name/location and service-category search, availability filters, public studio pages, and service/pricing profiles.
- Blouse design catalogue with seeded sample designs.
- Customer order placement with address, design, fabric/instructions, measurement review, private reference-image upload, and immutable order snapshots.
- Idempotent order submission, customer order history, cancellation before acceptance, repeat orders, and receipt confirmation.
- Tailor accept/reject and stitching workflow with recorded status history and in-app notifications.
- Delivery partner availability, atomic assignment claiming, and separate pickup/delivery status history.
- Responsive customer, tailor and delivery dashboards with pagination, search, and status filters.
- SQLite persistence with SQLAlchemy; no external database required to start.
- Bounded image upload validation and private local reference-image storage.
- Health endpoint and automated workflow tests.

## Requirements

- Python 3.10+
- Windows, macOS or Linux

## Run on Windows PowerShell

```powershell
cd stitch-it-fullpython
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
py -c "import secrets; print(secrets.token_urlsafe(48))"
# Paste the generated value into .env as SECRET_KEY.
uvicorn app.main:app --reload
```

If PowerShell blocks activation, run:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Run on macOS/Linux

```bash
cd stitch-it-fullpython
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
# Paste the generated value into .env as SECRET_KEY.
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## First-use walkthrough

1. Register a customer account.
2. In another browser/private window, register a tailor account and add services/pricing from the tailor dashboard.
3. Sign in as the customer, save an address and (optionally) a manual measurement profile, then create an order.
4. Sign in as the tailor to accept/reject and update the order status.
5. Register a delivery-partner account. Once a tailor marks an order ready, the delivery partner dashboard lists eligible deliveries and allows claiming one.
6. Advance the delivery through `picked_up`, `in_transit`, and `delivered`; the customer can then confirm receipt.

The first run seeds a small blouse-design catalogue. You can register all three roles yourself for local testing.

## Configuration

The application loads `.env` from the project root and refuses to start unless `SECRET_KEY` is a unique random value of at least 32 characters. Generate one with the command above, then paste it into `.env`. Never reuse the sample value or commit `.env`. `DATABASE_URL` defaults to local SQLite. For a shared deployment, configure a managed database and persistent file storage; do not use ephemeral local disk for customer uploads. Set `SESSION_HTTPS_ONLY=true` for HTTPS deployments.

## Important production checklist

- Set a unique `SECRET_KEY`; use HTTPS and secure cookie settings behind a trusted proxy.
- Add email verification, password reset, rate limiting, and operational audit logging.
- Use managed object storage with private access and retention/deletion controls for customer photos.
- Add admin review/moderation and dispute/refund workflows.
- Integrate Razorpay server-side order creation, signature verification and webhooks before accepting real money.
- Validate every body-measurement output against tape-measured ground truth across body types, camera devices, poses and lighting. Never send unvalidated AI estimates directly to production stitching.
- Implement and validate an actual computer-vision service (MediaPipe/OpenCV/SMPL-X) separately. Current measurements are manually entered in centimetres; no AI-derived measurements or accuracy claims are supported.
- Add formal database migrations before upgrading a deployed database. New marketplace tables are created additively; existing database tables are not altered automatically.
- Add integration tests, backups, monitoring and security review before public launch.

Install the test dependencies with `pip install -r requirements-dev.txt`, then run tests with `python -m pytest`.

## Project structure

```text
stitch-it-fullpython/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── security.py
│   ├── services.py
│   ├── templates/
│   └── static/
├── tests/
├── .env.example
├── requirements.txt
└── README.md
```

## API / system endpoints

- `GET /health` — health check.
- `GET /docs` — FastAPI-generated API documentation.
- Browser workflows use server-rendered routes and signed session cookies.

## Reset local development data

Stop the server and delete `stitch_it.db`. The next start creates a fresh database and seeds sample designs.
