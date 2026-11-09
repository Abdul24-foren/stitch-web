# Stitch It — Full-Python MVP

**Measure Right. Stitch Smart. Deliver Perfect.**

A runnable starter marketplace built with **Python FastAPI + Jinja2 + SQLite + HTML/CSS/JavaScript**. It provides one website with separate customer, tailor and delivery-partner role portals.

> This is a functional MVP foundation, not a production-certified tailoring or measurement system. AI measurements, live payment collection, email/SMS, and production delivery integrations require additional implementation, credentials and real-world validation.

## Features included

- Customer, tailor and delivery-partner registration/login.
- Secure password hashing (PBKDF2-HMAC-SHA256) and signed session cookies.
- Role-protected dashboards and server-side authorization.
- Tailor directory and service/pricing profiles.
- Blouse design catalogue with seeded sample designs.
- Customer order placement with optional measurement notes.
- Tailor accept/reject and stitching-status workflow.
- Delivery assignment and pickup/delivery status workflow.
- Order history and responsive UI.
- SQLite persistence with SQLAlchemy; no external database required to start.
- Image upload validation and local storage foundation.
- Health endpoint and basic automated tests.

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
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## First-use walkthrough

1. Register a customer account.
2. In another browser/private window, register a tailor account and add services/pricing from the tailor dashboard.
3. Sign in as the customer, browse tailors and create an order.
4. Sign in as the tailor to accept/reject and update the order status.
5. Register a delivery-partner account. A tailor can mark an accepted order as `ready_for_pickup`; the delivery partner dashboard lists eligible orders and allows claiming them.
6. Update delivery to `picked_up` and `delivered`.

The first run seeds a small blouse-design catalogue. You can register all three roles yourself for local testing.

## Configuration

Copy `.env.example` to `.env`. `SECRET_KEY` must be changed to a long random value before deployment. `DATABASE_URL` defaults to local SQLite. For a shared deployment, configure a managed database and persistent file storage; do not use ephemeral local disk for customer uploads.

## Important production checklist

- Set a unique `SECRET_KEY`; use HTTPS and secure cookie settings behind a trusted proxy.
- Add email verification, password reset, rate limiting, audit logging and CSRF protection.
- Use managed object storage with private access and retention/deletion controls for customer photos.
- Add admin review/moderation and dispute/refund workflows.
- Integrate Razorpay server-side order creation, signature verification and webhooks before accepting real money.
- Validate every body-measurement output against tape-measured ground truth across body types, camera devices, poses and lighting. Never send unvalidated AI estimates directly to production stitching.
- Implement an actual computer-vision service (MediaPipe/OpenCV/SMPL-X) separately. The current measurement endpoint is deliberately labelled as a manual/placeholder workflow; it does not claim to calculate accurate body measurements.
- Add integration tests, backups, monitoring and security review before public launch.

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
