from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO
import json
import math
import secrets
import uuid
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, String
from sqlalchemy.exc import IntegrityError
from email_validator import validate_email, EmailNotValidError
from .config import APP_NAME, SECRET_KEY, SESSION_HTTPS_ONLY, UPLOAD_DIR, MAX_UPLOAD_MB
from .database import Base, engine, get_db
from .models import (
    User,
    TailorProfile,
    Design,
    Order,
    Delivery,
    Measurement,
    CustomerAddress,
    TailorBusinessProfile,
    DeliveryPartnerProfile,
    TailorService,
    ReferenceImage,
    OrderDetail,
    OrderSubmission,
    OrderStatusEvent,
    DeliveryStatusEvent,
    Notification,
    utcnow,
)
from .security import hash_password, verify_password, current_user
from .services import (
    ORDER_TRANSITIONS,
    ensure_default_tailor_service,
    mark_notifications_read,
    seed_designs,
    transition_order,
)

BASE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        seed_designs(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title=APP_NAME,
    version="1.0.0",
    description="Stitch It tailoring marketplace MVP",
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

def page(request: Request, name: str, **context):
    csrf_token = request.session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return templates.TemplateResponse(
        request=request,
        name=name,
        context={
            "request": request,
            "user": current_user(request),
            "csrf_token": csrf_token,
            "idempotency_key": uuid.uuid4().hex,
            **context,
        },
    )


async def verify_csrf(request: Request):
    form = await request.form()
    supplied = form.get("csrf_token")
    expected = request.session.get("csrf_token")
    if not isinstance(supplied, str) or not isinstance(expected, str) or not secrets.compare_digest(
        supplied, expected
    ):
        raise HTTPException(403, "The form security token is invalid or expired. Reload and try again.")


def notify(db: Session, recipient_id: int, message: str, order_id: int | None = None):
    db.add(Notification(recipient_id=recipient_id, order_id=order_id, message=message))


def _owned_order(db: Session, order_id: int, user: dict) -> Order:
    query = db.query(Order).filter(Order.id == order_id)
    if user["role"] == "customer":
        query = query.filter(Order.customer_id == user["id"])
    elif user["role"] == "tailor":
        query = query.filter(Order.tailor_id == user["id"])
    elif user["role"] == "delivery":
        query = query.join(Delivery).filter(Delivery.partner_id == user["id"])
    else:
        raise HTTPException(403, "You do not have permission to access this order.")
    order = query.first()
    if not order:
        raise HTTPException(404, "Order not found.")
    return order


async def _store_reference_image(image: UploadFile, owner_id: int, db: Session) -> ReferenceImage:
    accepted_types = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if image.content_type not in accepted_types:
        raise HTTPException(400, "Only JPG, PNG or WebP images are accepted.")
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    content = await image.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(413, "Image exceeds upload size limit.")
    from PIL import Image

    try:
        with Image.open(BytesIO(content)) as img:
            expected_format = {
                "image/jpeg": "JPEG",
                "image/png": "PNG",
                "image/webp": "WEBP",
            }[image.content_type]
            if img.format != expected_format or img.width * img.height > 30_000_000:
                raise HTTPException(400, "The image format or dimensions are not supported.")
            img.verify()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "The uploaded file is not a valid image.") from exc

    filename = f"{uuid.uuid4().hex}{accepted_types[image.content_type]}"
    (UPLOAD_DIR / filename).write_bytes(content)
    reference = ReferenceImage(
        owner_id=owner_id,
        filename=filename,
        content_type=image.content_type,
    )
    db.add(reference)
    db.flush()
    return reference

def require_user(request: Request, role: str | None = None):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in first.")
    if role and user.get("role") != role:
        raise HTTPException(status_code=403, detail="You do not have permission to access this page.")
    return user

def redirect(path: str):
    return RedirectResponse(path, status_code=303)

@app.get("/health")
def health():
    return {"status": "ok", "service": APP_NAME}

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    designs = db.query(Design).all()
    tailors = db.query(TailorProfile).filter_by(available=1).all()
    return page(request, "index.html", designs=designs, tailors=tailors)

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return page(request, "register.html")

@app.post("/register")
def register(request: Request, name: str = Form(...), email: str = Form(...), password: str = Form(...),
             role: str = Form(...), phone: str = Form(""),
             _csrf: None = Depends(verify_csrf)):
    name, email, role = name.strip(), email.strip().lower(), role.strip()
    if role not in {"customer", "tailor", "delivery"}:
        return page(request, "register.html", error="Choose a valid account type.")
    if not 2 <= len(name) <= 120 or not 8 <= len(password) <= 256:
        return page(
            request,
            "register.html",
            error="Name must be 2–120 characters and password 8–256 characters.",
        )
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        return page(request, "register.html", error="Enter a valid email address.")
    db = next(get_db())
    try:
        if db.query(User).filter_by(email=email).first():
            return page(request, "register.html", error="An account with this email already exists.")
        user = User(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role=role,
            phone=phone.strip()[:30],
        )
        db.add(user); db.flush()
        if role == "tailor":
            profile = TailorProfile(
                user_id=user.id,
                shop_name=f"{name}'s Studio",
                location="",
                blouse_price=500,
            )
            db.add(profile)
            db.flush()
            db.add(TailorBusinessProfile(user_id=user.id))
            ensure_default_tailor_service(db, user, profile)
        elif role == "delivery":
            db.add(DeliveryPartnerProfile(user_id=user.id))
        db.commit()
        request.session.clear()
        request.session["user"] = {"id": user.id, "name": user.name, "email": user.email, "role": user.role}
        request.session["csrf_token"] = secrets.token_urlsafe(32)
        return redirect("/dashboard")
    except IntegrityError:
        db.rollback()
        return page(request, "register.html", error="An account with this email already exists.")
    finally:
        db.close()

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return page(request, "login.html")

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...),
          _csrf: None = Depends(verify_csrf)):
    db = next(get_db())
    try:
        user = db.query(User).filter_by(email=email.strip().lower()).first()
        if not user or not verify_password(password, user.password_hash):
            return page(request, "login.html", error="Incorrect email or password.")
        request.session.clear()
        request.session["user"] = {"id": user.id, "name": user.name, "email": user.email, "role": user.role}
        request.session["csrf_token"] = secrets.token_urlsafe(32)
        return redirect("/dashboard")
    finally:
        db.close()

@app.post("/logout")
def logout(request: Request, _csrf: None = Depends(verify_csrf)):
    request.session.clear()
    return redirect("/")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    page_number: int = Query(1, ge=1),
    status_filter: str = "",
    search: str = "",
    db: Session = Depends(get_db),
):
    user = require_user(request)
    role, uid = user["role"], user["id"]
    notifications = db.query(Notification).filter_by(recipient_id=uid).order_by(
        Notification.created_at.desc()
    ).limit(10).all()
    if role == "customer":
        query = db.query(Order).filter_by(customer_id=uid)
        total_orders = query.count()
        active_statuses = {"pending", "accepted", "cutting", "stitching", "quality_check",
                           "ready_for_pickup", "out_for_delivery"}
        stats = {
            "total": total_orders,
            "pending": query.filter_by(status="pending").count(),
            "active": query.filter(Order.status.in_(active_statuses)).count(),
            "completed": query.filter(Order.status == "completed").count(),
        }
        orders = query.order_by(Order.created_at.desc()).offset((page_number - 1) * 10).limit(10).all()
        return page(
            request,
            "customer_dashboard.html",
            orders=orders,
            designs=db.query(Design).all(),
            tailors=db.query(TailorProfile).filter_by(available=1).all(),
            measurements=db.query(Measurement).filter_by(customer_id=uid)
            .order_by(Measurement.created_at.desc()).all(),
            used_measurement_ids={
                row[0] for row in db.query(Order.measurement_id).filter(
                    Order.customer_id == uid, Order.measurement_id.is_not(None)
                ).all()
            },
            addresses=db.query(CustomerAddress).filter_by(customer_id=uid)
            .order_by(CustomerAddress.is_default.desc(), CustomerAddress.created_at.desc()).all(),
            profile=db.query(User).filter_by(id=uid).first(),
            stats=stats,
            page_number=page_number,
            has_next=total_orders > page_number * 10,
            notifications=notifications,
        )
    if role == "tailor":
        query = db.query(Order).filter_by(tailor_id=uid)
        if status_filter and status_filter in ORDER_TRANSITIONS:
            query = query.filter_by(status=status_filter)
        if search.strip():
            query = query.join(User, User.id == Order.customer_id).filter(
                or_(User.name.ilike(f"%{search.strip()[:80]}%"),
                    Order.id.cast(String).ilike(f"%{search.strip()[:80]}%"))
            )
        total_orders = query.count()
        orders = query.order_by(Order.created_at.desc()).offset((page_number - 1) * 10).limit(10).all()
        profile = db.query(TailorProfile).filter_by(user_id=uid).first()
        stats = {
            "pending": db.query(Order).filter_by(tailor_id=uid, status="pending").count(),
            "accepted": db.query(Order).filter_by(tailor_id=uid, status="accepted").count(),
            "active": db.query(Order).filter(
                Order.tailor_id == uid,
                Order.status.in_(["cutting", "stitching", "quality_check"]),
            ).count(),
            "ready": db.query(Order).filter_by(tailor_id=uid, status="ready_for_pickup").count(),
            "completed": db.query(Order).filter_by(tailor_id=uid, status="completed").count(),
        }
        order_measurements = {
            order.id: json.loads(order.order_details.measurement_snapshot)
            for order in orders
            if order.order_details and order.order_details.measurement_snapshot
        }
        return page(
            request,
            "tailor_dashboard.html",
            orders=orders,
            profile=profile,
            business=db.query(TailorBusinessProfile).filter_by(user_id=uid).first(),
            services=db.query(TailorService).filter_by(tailor_id=uid).all(),
            stats=stats,
            notifications=notifications,
            page_number=page_number,
            has_next=total_orders > page_number * 10,
            status_filter=status_filter,
            search=search,
            order_measurements=order_measurements,
            next_order_status={
                "accepted": "cutting",
                "cutting": "stitching",
                "stitching": "quality_check",
                "quality_check": "ready_for_pickup",
            },
        )
    deliveries = db.query(Delivery).filter(
        or_(
            Delivery.partner_id == uid,
            and_(
                Delivery.partner_id.is_(None),
                Delivery.order.has(Order.status == "ready_for_pickup"),
            ),
        )
    ).order_by(Delivery.updated_at.desc()).all()
    profile = db.query(DeliveryPartnerProfile).filter_by(user_id=uid).first()
    delivery_details = {}
    for delivery in deliveries:
        detail = db.query(OrderDetail).filter_by(order_id=delivery.order_id).first()
        delivery_details[delivery.id] = {
            "reference": detail.order_reference if detail else f"Order #{delivery.order_id}",
            "address": json.loads(detail.address_snapshot) if detail else {},
        }
    return page(
        request,
        "delivery_dashboard.html",
        deliveries=deliveries,
        profile=profile,
        delivery_details=delivery_details,
        stats={
            "available": sum(1 for item in deliveries if item.partner_id is None),
            "active": sum(1 for item in deliveries if item.partner_id == uid and item.status not in {"delivered", "failed"}),
            "completed": db.query(Delivery).filter_by(partner_id=uid, status="delivered").count(),
        },
        notifications=notifications,
    )

@app.post("/tailor/profile")
def update_profile(request: Request, shop_name: str = Form(...), location: str = Form(...),
                   bio: str = Form(""), blouse_price: float = Form(...),
                   shop_address: str = Form(""), experience_years: int = Form(0),
                   working_hours: str = Form(""), available: bool = Form(False),
                   db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    user = require_user(request, "tailor")
    if not math.isfinite(blouse_price) or blouse_price < 0 or experience_years < 0:
        raise HTTPException(400, "Enter a valid non-negative price.")
    profile = db.query(TailorProfile).filter_by(user_id=user["id"]).first()
    profile.shop_name = shop_name.strip()[:140]
    profile.location = location.strip()[:180]
    profile.bio = bio.strip()[:2000]
    profile.blouse_price = blouse_price
    profile.available = int(available)
    business = db.query(TailorBusinessProfile).filter_by(user_id=user["id"]).first()
    if business is None:
        business = TailorBusinessProfile(user_id=user["id"])
        db.add(business)
    business.shop_address = shop_address.strip()[:300]
    business.experience_years = min(experience_years, 80)
    business.working_hours = working_hours.strip()[:200]
    ensure_default_tailor_service(db, db.query(User).filter_by(id=user["id"]).one(), profile)
    default_service = db.query(TailorService).filter_by(
        tailor_id=user["id"], name="Saree blouse stitching"
    ).first()
    if default_service:
        default_service.price = blouse_price
        default_service.active = bool(available)
    db.commit()
    return redirect("/dashboard")

@app.post("/tailor/services")
def create_tailor_service(
    request: Request,
    name: str = Form(...),
    category: str = Form("Saree blouse"),
    price: float = Form(...),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "tailor")
    if not name.strip() or len(name) > 120 or len(category) > 80:
        raise HTTPException(400, "Enter a service name and category within the length limits.")
    if not math.isfinite(price) or price < 0:
        raise HTTPException(400, "Enter a valid non-negative price.")
    db.add(
        TailorService(
            tailor_id=user["id"],
            name=name.strip(),
            category=category.strip() or "Saree blouse",
            price=price,
        )
    )
    db.commit()
    return redirect("/dashboard")


@app.post("/tailor/services/{service_id}/availability")
def toggle_tailor_service(
    service_id: int,
    request: Request,
    active: bool = Form(False),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "tailor")
    service = db.query(TailorService).filter_by(
        id=service_id, tailor_id=user["id"]
    ).first()
    if not service:
        raise HTTPException(404, "Service not found.")
    service.active = active
    db.commit()
    return redirect("/dashboard")


@app.post("/customer/profile")
def update_customer_profile(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "customer")
    name = name.strip()
    if not 2 <= len(name) <= 120 or len(phone) > 30:
        raise HTTPException(400, "Enter a name between 2 and 120 characters and a phone up to 30 characters.")
    profile = db.query(User).filter_by(id=user["id"], role="customer").first()
    profile.name, profile.phone = name, phone.strip()
    db.commit()
    request.session["user"]["name"] = name
    return redirect("/dashboard")


@app.post("/delivery/profile")
def update_delivery_profile(
    request: Request,
    available: bool = Form(False),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "delivery")
    profile = db.query(DeliveryPartnerProfile).filter_by(user_id=user["id"]).first()
    if profile is None:
        profile = DeliveryPartnerProfile(user_id=user["id"])
        db.add(profile)
    profile.available = available
    db.commit()
    return redirect("/dashboard")


@app.post("/addresses")
def create_address(
    request: Request,
    label: str = Form("Home"),
    recipient_name: str = Form(...),
    phone: str = Form(...),
    address_line: str = Form(...),
    city: str = Form(...),
    postal_code: str = Form(""),
    make_default: bool = Form(False),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "customer")
    fields = [label, recipient_name, phone, address_line, city, postal_code]
    limits = [60, 120, 30, 300, 120, 20]
    if any(len(value.strip()) > limit for value, limit in zip(fields, limits)):
        raise HTTPException(400, "One or more address fields exceed the allowed length.")
    if not recipient_name.strip() or not phone.strip() or not address_line.strip() or not city.strip():
        raise HTTPException(400, "Recipient, phone, street address, and city are required.")
    if db.query(CustomerAddress).filter_by(customer_id=user["id"]).count() >= 10:
        raise HTTPException(400, "You can save up to 10 delivery addresses.")
    is_first = not db.query(CustomerAddress).filter_by(customer_id=user["id"]).first()
    if make_default or is_first:
        db.query(CustomerAddress).filter_by(customer_id=user["id"]).update(
            {"is_default": False}, synchronize_session=False
        )
    db.add(
        CustomerAddress(
            customer_id=user["id"],
            label=label.strip()[:60] or "Home",
            recipient_name=recipient_name.strip(),
            phone=phone.strip(),
            address_line=address_line.strip(),
            city=city.strip(),
            postal_code=postal_code.strip(),
            is_default=make_default or is_first,
        )
    )
    db.commit()
    return redirect("/dashboard")


@app.post("/addresses/{address_id}/default")
def set_default_address(
    address_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "customer")
    address = db.query(CustomerAddress).filter_by(
        id=address_id, customer_id=user["id"]
    ).first()
    if not address:
        raise HTTPException(404, "Address not found.")
    db.query(CustomerAddress).filter_by(customer_id=user["id"]).update(
        {"is_default": False}, synchronize_session=False
    )
    address.is_default = True
    db.commit()
    return redirect("/dashboard")


@app.post("/addresses/{address_id}/delete")
def delete_address(
    address_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "customer")
    address = db.query(CustomerAddress).filter_by(
        id=address_id, customer_id=user["id"]
    ).first()
    if not address:
        raise HTTPException(404, "Address not found.")
    if db.query(OrderDetail).filter_by(address_id=address.id).first():
        raise HTTPException(409, "This address is retained with an existing order and cannot be deleted.")
    was_default = address.is_default
    db.delete(address)
    if was_default:
        replacement = db.query(CustomerAddress).filter_by(
            customer_id=user["id"]
        ).order_by(CustomerAddress.created_at.asc()).first()
        if replacement:
            replacement.is_default = True
    db.commit()
    return redirect("/dashboard")


@app.post("/measurements")
def save_measurements(request: Request, label: str = Form("My measurements"), notes: str = Form(""),
                      bust: float | None = Form(None), waist: float | None = Form(None),
                      shoulder: float | None = Form(None), armhole: float | None = Form(None),
                      db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    user = require_user(request, "customer")
    values = [v for v in (bust, waist, shoulder, armhole) if v is not None]
    if not values:
        raise HTTPException(400, "Enter at least one measurement.")
    if any(not math.isfinite(v) or v <= 0 or v > 250 for v in values):
        raise HTTPException(400, "Measurements must be between 0 and 250 cm.")
    db.add(Measurement(customer_id=user["id"], label=label.strip()[:100] or "My measurements",
                       notes=notes.strip()[:2000], bust=bust, waist=waist,
                       shoulder=shoulder, armhole=armhole))
    db.commit()
    return redirect("/dashboard")


@app.post("/measurements/{measurement_id}")
def update_measurement(
    measurement_id: int,
    request: Request,
    label: str = Form(...),
    notes: str = Form(""),
    bust: float | None = Form(None),
    waist: float | None = Form(None),
    shoulder: float | None = Form(None),
    armhole: float | None = Form(None),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "customer")
    measurement = db.query(Measurement).filter_by(
        id=measurement_id, customer_id=user["id"]
    ).first()
    if not measurement:
        raise HTTPException(404, "Measurement profile not found.")
    values = [value for value in (bust, waist, shoulder, armhole) if value is not None]
    if not values or any(not math.isfinite(value) or value <= 0 or value > 250 for value in values):
        raise HTTPException(400, "Enter at least one measurement between 0 and 250 cm.")
    measurement.label = label.strip()[:100] or "My measurements"
    measurement.notes = notes.strip()[:2000]
    measurement.bust, measurement.waist = bust, waist
    measurement.shoulder, measurement.armhole = shoulder, armhole
    db.commit()
    return redirect("/dashboard")


@app.post("/measurements/{measurement_id}/delete")
def delete_measurement(
    measurement_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "customer")
    measurement = db.query(Measurement).filter_by(
        id=measurement_id, customer_id=user["id"]
    ).first()
    if not measurement:
        raise HTTPException(404, "Measurement profile not found.")
    if db.query(Order).filter_by(measurement_id=measurement_id).first():
        raise HTTPException(409, "This profile is retained with an existing order and cannot be deleted.")
    db.delete(measurement)
    db.commit()
    return redirect("/dashboard")


@app.post("/orders")
async def create_order(
    request: Request,
    tailor_id: int = Form(...),
    design_id: int = Form(...),
    notes: str = Form(""),
    fabric_details: str = Form(""),
    garment_type: str = Form("Saree blouse"),
    measurement_id: int | None = Form(None),
    measurement_notes: str = Form(""),
    manual_bust: float | None = Form(None),
    manual_waist: float | None = Form(None),
    manual_shoulder: float | None = Form(None),
    manual_armhole: float | None = Form(None),
    manual_sleeve_length: float | None = Form(None),
    manual_neck: float | None = Form(None),
    manual_blouse_length: float | None = Form(None),
    address_id: int | None = Form(None),
    reference_image_id: int | None = Form(None),
    submission_key: str = Form(...),
    image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "customer")
    submission_key = submission_key.strip()
    if not submission_key or len(submission_key) > 64:
        raise HTTPException(400, "Order form token is invalid. Reload the page and try again.")
    existing_submission = db.query(OrderSubmission).filter_by(
        customer_id=user["id"], idempotency_key=submission_key
    ).first()
    if existing_submission:
        return redirect(f"/orders/{existing_submission.order_id}")

    tailor = db.query(User).filter_by(id=tailor_id, role="tailor").first()
    profile = db.query(TailorProfile).filter_by(user_id=tailor_id, available=1).first()
    design = db.query(Design).filter_by(id=design_id).first()
    if not tailor or not profile or not design:
        raise HTTPException(400, "Select a valid tailor and design.")
    if not garment_type.strip() or len(garment_type) > 100 or len(fabric_details) > 1000 or len(notes) > 3000:
        raise HTTPException(400, "Garment, fabric, or instruction details exceed the allowed length.")
    measurement = None
    manual_measurements = {
        "bust": manual_bust,
        "waist": manual_waist,
        "shoulder": manual_shoulder,
        "armhole": manual_armhole,
        "sleeve_length": manual_sleeve_length,
        "neck": manual_neck,
        "blouse_length": manual_blouse_length,
    }
    entered_manual_measurements = {
        key: value for key, value in manual_measurements.items() if value is not None
    }
    if any(
        not math.isfinite(value) or value <= 0 or value > 250
        for value in entered_manual_measurements.values()
    ):
        raise HTTPException(400, "Manual measurements must be between 0 and 250 cm.")
    if measurement_id is not None:
        measurement = db.query(Measurement).filter_by(
            id=measurement_id, customer_id=user["id"]
        ).first()
        if not measurement:
            raise HTTPException(400, "Select one of your saved measurement profiles.")
        if entered_manual_measurements:
            raise HTTPException(400, "Choose saved measurements or enter manual measurements, not both.")
    if len(measurement_notes) > 1000:
        raise HTTPException(400, "Measurement notes must be 1000 characters or fewer.")
    address = None
    if address_id is not None:
        address = db.query(CustomerAddress).filter_by(
            id=address_id, customer_id=user["id"]
        ).first()
        if not address:
            raise HTTPException(400, "Select one of your saved delivery addresses.")
    else:
        raise HTTPException(400, "Save and select a delivery address before placing an order.")
    if image is not None and reference_image_id is not None:
        raise HTTPException(400, "Select one design reference image at a time.")
    reference = None
    if reference_image_id is not None:
        reference = db.query(ReferenceImage).filter_by(
            id=reference_image_id, owner_id=user["id"]
        ).first()
        if not reference:
            raise HTTPException(400, "Selected design reference was not found.")
    created_filename = None
    try:
        if image is not None and image.filename:
            reference = await _store_reference_image(image, user["id"], db)
            created_filename = reference.filename
        order = Order(
            customer_id=user["id"],
            tailor_id=tailor_id,
            design_id=design_id,
            measurement_id=measurement.id if measurement else None,
            notes=notes.strip()[:3000],
            amount=float(profile.blouse_price + design.base_price),
        )
        db.add(order)
        db.flush()
        address_snapshot = {
            "recipient_name": address.recipient_name,
            "phone": address.phone,
            "address_line": address.address_line,
            "city": address.city,
            "postal_code": address.postal_code,
        } if address else {}
        measurement_snapshot = {
            field: getattr(measurement, field)
            for field in ("bust", "waist", "shoulder", "armhole", "notes")
        } if measurement else {
            **entered_manual_measurements,
            "notes": measurement_notes.strip()[:1000],
        }
        db.add(
            OrderDetail(
                order_id=order.id,
                order_reference=f"ST-{utcnow():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
                garment_type=garment_type.strip()[:100],
                fabric_details=fabric_details.strip()[:1000],
                instructions=notes.strip()[:3000],
                measurement_snapshot=json.dumps(measurement_snapshot),
                reference_image_id=reference.id if reference else None,
                address_id=address.id if address else None,
                address_snapshot=json.dumps(address_snapshot),
                price_breakdown=json.dumps(
                    {"stitching": profile.blouse_price, "design": design.base_price}
                ),
                payment_status="payment_pending",
            )
        )
        db.add(Delivery(order_id=order.id))
        db.add(OrderSubmission(
            customer_id=user["id"],
            idempotency_key=submission_key,
            order_id=order.id,
        ))
        db.add(OrderStatusEvent(
            order_id=order.id,
            status="pending",
            actor_id=user["id"],
            note="Order placed",
        ))
        notify(db, tailor_id, f"New order #{order.id} is waiting for your response.", order.id)
        db.commit()
        return redirect(f"/orders/{order.id}")
    except IntegrityError:
        db.rollback()
        existing_submission = db.query(OrderSubmission).filter_by(
            customer_id=user["id"], idempotency_key=submission_key
        ).first()
        if existing_submission:
            return redirect(f"/orders/{existing_submission.order_id}")
        if created_filename:
            (UPLOAD_DIR / created_filename).unlink(missing_ok=True)
        raise HTTPException(409, "The order could not be saved because its data conflicted. Reload and retry.")
    except Exception:
        db.rollback()
        if created_filename:
            (UPLOAD_DIR / created_filename).unlink(missing_ok=True)
        raise

@app.post("/orders/{order_id}/decision")
def order_decision(
    order_id: int,
    request: Request,
    decision: str = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "tailor")
    order = db.query(Order).filter_by(id=order_id, tailor_id=user["id"]).first()
    if not order or order.status != "pending":
        raise HTTPException(404, "Pending order not found.")
    if decision not in {"accepted", "rejected"}:
        raise HTTPException(400, "Invalid decision.")
    if decision == "rejected" and not reason.strip():
        raise HTTPException(400, "Provide a reason when rejecting an order.")
    transition_order(db, order, decision, user["id"], reason.strip()[:500])
    db.commit()
    return redirect(f"/orders/{order.id}")

@app.post("/orders/{order_id}/status")
def order_status(
    order_id: int,
    request: Request,
    status: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "tailor")
    order = db.query(Order).filter_by(id=order_id, tailor_id=user["id"]).first()
    if not order:
        raise HTTPException(404, "Order not found.")
    if status not in {"cutting", "stitching", "quality_check", "ready_for_pickup"}:
        raise HTTPException(400, "Invalid order status.")
    try:
        transition_order(db, order, status, user["id"], note.strip()[:500])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return redirect(f"/orders/{order.id}")


@app.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: int,
    request: Request,
    reason: str = Form(""),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "customer")
    order = db.query(Order).filter_by(id=order_id, customer_id=user["id"]).first()
    if not order:
        raise HTTPException(404, "Order not found.")
    try:
        transition_order(db, order, "cancelled", user["id"], reason.strip()[:500])
    except ValueError as exc:
        raise HTTPException(400, "Only pending or accepted orders can be cancelled.") from exc
    db.commit()
    return redirect(f"/orders/{order.id}")


@app.post("/orders/{order_id}/confirm")
def confirm_order_receipt(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "customer")
    order = db.query(Order).filter_by(id=order_id, customer_id=user["id"]).first()
    if not order:
        raise HTTPException(404, "Order not found.")
    try:
        transition_order(db, order, "completed", user["id"], "Customer confirmed receipt")
    except ValueError as exc:
        raise HTTPException(400, "Order cannot be completed before delivery.") from exc
    db.commit()
    return redirect(f"/orders/{order.id}")

@app.post("/deliveries/{delivery_id}/claim")
def claim_delivery(
    delivery_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "delivery")
    profile = db.query(DeliveryPartnerProfile).filter_by(user_id=user["id"]).first()
    if profile is not None and not profile.available:
        raise HTTPException(403, "Set your delivery availability to active before claiming an assignment.")
    claimed = db.query(Delivery).filter(
        Delivery.id == delivery_id,
        Delivery.partner_id.is_(None),
        Delivery.order.has(Order.status == "ready_for_pickup"),
    ).update(
        {Delivery.partner_id: user["id"], Delivery.status: "assigned"},
        synchronize_session=False,
    )
    if claimed != 1:
        raise HTTPException(404, "Available delivery not found.")
    delivery = db.query(Delivery).filter_by(id=delivery_id, partner_id=user["id"]).one()
    delivery.updated_at = utcnow()
    db.add(DeliveryStatusEvent(
        delivery_id=delivery.id,
        status="assigned",
        actor_id=user["id"],
        note="Assignment accepted",
    ))
    notify(db, delivery.order.customer_id, f"Delivery partner accepted order #{delivery.order_id}.", delivery.order_id)
    notify(db, delivery.order.tailor_id, f"Delivery partner accepted order #{delivery.order_id}.", delivery.order_id)
    db.commit()
    return redirect("/dashboard")

@app.post("/deliveries/{delivery_id}/status")
def delivery_status(
    delivery_id: int,
    request: Request,
    status: str = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "delivery")
    delivery = db.query(Delivery).filter_by(id=delivery_id, partner_id=user["id"]).first()
    if not delivery:
        raise HTTPException(404, "Delivery not found.")
    allowed = {
        "assigned": {"arrived_at_tailor"},
        "arrived_at_tailor": {"picked_up"},
        "picked_up": {"out_for_delivery"},
        "out_for_delivery": {"arrived_at_customer", "failed"},
        "arrived_at_customer": {"delivered", "failed"},
        "failed": {"out_for_delivery"},
    }
    if status not in allowed.get(delivery.status, set()):
        raise HTTPException(400, f"Invalid delivery transition from {delivery.status} to {status}.")
    if status == "failed" and not reason.strip():
        raise HTTPException(400, "Provide a reason when marking a delivery failed.")
    changed = db.query(Delivery).filter(
        Delivery.id == delivery.id,
        Delivery.partner_id == user["id"],
        Delivery.status == delivery.status,
    ).update(
        {"status": status, "updated_at": utcnow()},
        synchronize_session=False,
    )
    if changed != 1:
        raise HTTPException(409, "Delivery status changed concurrently; reload and try again.")
    delivery.status = status
    delivery.updated_at = utcnow()
    db.add(DeliveryStatusEvent(
        delivery_id=delivery.id,
        status=status,
        actor_id=user["id"],
        note=reason.strip()[:500],
    ))
    order = delivery.order
    if status == "out_for_delivery":
        if order.status == "ready_for_pickup":
            try:
                transition_order(db, order, "out_for_delivery", user["id"])
            except ValueError as exc:
                raise HTTPException(400, "Order is not ready for delivery.") from exc
        elif order.status == "out_for_delivery":
            notify(db, order.customer_id, f"Delivery retry started for order #{order.id}.", order.id)
            notify(db, order.tailor_id, f"Delivery retry started for order #{order.id}.", order.id)
        else:
            raise HTTPException(400, "Order is not ready for delivery.")
    elif status == "delivered":
        transition_order(db, order, "delivered", user["id"])
    else:
        notify(db, order.customer_id, f"Delivery for order #{order.id}: {status.replace('_', ' ')}.", order.id)
        notify(db, order.tailor_id, f"Delivery for order #{order.id}: {status.replace('_', ' ')}.", order.id)
    db.commit()
    return redirect("/dashboard")

@app.post("/upload-reference")
async def upload_reference(
    request: Request,
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "customer")
    try:
        reference = await _store_reference_image(image, user["id"], db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return JSONResponse({
        "message": "Reference image saved. AI measurement is not performed by this MVP.",
        "file": reference.filename,
        "id": reference.id,
    })


@app.get("/tailors", response_class=HTMLResponse)
def list_tailors(
    request: Request,
    search: str = "",
    service: str = "",
    availability: str = "available",
    db: Session = Depends(get_db),
):
    if availability not in {"available", "unavailable", "all"}:
        availability = "available"
    query = db.query(TailorProfile).join(User).filter(User.role == "tailor")
    if availability == "available":
        query = query.filter(TailorProfile.available == 1)
    elif availability == "unavailable":
        query = query.filter(TailorProfile.available == 0)
    term = search.strip()[:80]
    if term:
        query = query.filter(
            or_(
                User.name.ilike(f"%{term}%"),
                TailorProfile.shop_name.ilike(f"%{term}%"),
                TailorProfile.location.ilike(f"%{term}%"),
            )
        )
    if service.strip():
        query = query.join(
            TailorService,
            TailorService.tailor_id == TailorProfile.user_id,
        ).filter(
            TailorService.active.is_(True),
            TailorService.category.ilike(f"%{service.strip()[:80]}%"),
        )
    tailors = query.order_by(TailorProfile.shop_name.asc()).distinct().all()
    return page(
        request,
        "tailors.html",
        tailors=tailors,
        search=term,
        service=service,
        availability=availability,
    )


@app.get("/tailors/{tailor_id}", response_class=HTMLResponse)
def tailor_detail(tailor_id: int, request: Request, db: Session = Depends(get_db)):
    profile = db.query(TailorProfile).filter_by(
        user_id=tailor_id, available=1
    ).first()
    if not profile:
        raise HTTPException(404, "Available tailor not found.")
    services = db.query(TailorService).filter_by(
        tailor_id=tailor_id, active=True
    ).all()
    return page(
        request,
        "tailor_detail.html",
        profile=profile,
        services=services,
        business=db.query(TailorBusinessProfile).filter_by(user_id=tailor_id).first(),
    )


@app.get("/orders/{order_id}", response_class=HTMLResponse)
def order_detail(order_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    order = _owned_order(db, order_id, user)
    details = db.query(OrderDetail).filter_by(order_id=order.id).first()
    events = db.query(OrderStatusEvent).filter_by(order_id=order.id).order_by(
        OrderStatusEvent.created_at.asc()
    ).all()
    delivery = db.query(Delivery).filter_by(order_id=order.id).first()
    delivery_events = db.query(DeliveryStatusEvent).filter_by(
        delivery_id=delivery.id
    ).order_by(DeliveryStatusEvent.created_at.asc()).all() if delivery else []
    return page(
        request,
        "order_detail.html",
        order=order,
        details=details,
        events=events,
        delivery=delivery,
        delivery_events=delivery_events,
        snapshot=json.loads(details.measurement_snapshot) if details else {},
        address=json.loads(details.address_snapshot) if details else {},
    )


@app.get("/orders/{order_id}/reference")
def order_reference(order_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    order = _owned_order(db, order_id, user)
    details = db.query(OrderDetail).filter_by(order_id=order.id).first()
    if not details or not details.reference_image:
        raise HTTPException(404, "No design reference is attached to this order.")
    image_path = UPLOAD_DIR / details.reference_image.filename
    if not image_path.is_file():
        raise HTTPException(404, "The design reference file is no longer available.")
    return FileResponse(image_path, media_type=details.reference_image.content_type)


@app.post("/notifications/read")
def read_notifications(
    request: Request,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request)
    mark_notifications_read(db, user["id"])
    db.commit()
    return redirect("/dashboard")


@app.post("/orders/{order_id}/repeat")
def repeat_order(
    order_id: int,
    request: Request,
    submission_key: str = Form(...),
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
):
    user = require_user(request, "customer")
    original = db.query(Order).filter_by(
        id=order_id, customer_id=user["id"]
    ).first()
    if not original:
        raise HTTPException(404, "Order not found.")
    submission_key = submission_key.strip()
    if not submission_key or len(submission_key) > 64:
        raise HTTPException(400, "Order form token is invalid. Reload and try again.")
    previous_submission = db.query(OrderSubmission).filter_by(
        customer_id=user["id"], idempotency_key=submission_key
    ).first()
    if previous_submission:
        return redirect(f"/orders/{previous_submission.order_id}")
    original_details = db.query(OrderDetail).filter_by(order_id=order_id).first()
    profile = db.query(TailorProfile).filter_by(
        user_id=original.tailor_id, available=1
    ).first()
    if not profile:
        raise HTTPException(409, "This tailor is currently unavailable.")
    repeated = Order(
        customer_id=user["id"],
        tailor_id=original.tailor_id,
        design_id=original.design_id,
        measurement_id=original.measurement_id,
        notes=original.notes,
        amount=float(profile.blouse_price + original.design.base_price),
    )
    db.add(repeated)
    db.flush()
    db.add(Delivery(order_id=repeated.id))
    db.add(OrderSubmission(
        customer_id=user["id"],
        idempotency_key=submission_key,
        order_id=repeated.id,
    ))
    db.add(OrderStatusEvent(
        order_id=repeated.id, status="pending", actor_id=user["id"], note="Repeated order"
    ))
    if original_details:
        db.add(OrderDetail(
            order_id=repeated.id,
            order_reference=f"ST-{utcnow():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}",
            garment_type=original_details.garment_type,
            fabric_details=original_details.fabric_details,
            instructions=original_details.instructions,
            measurement_snapshot=original_details.measurement_snapshot,
            reference_image_id=original_details.reference_image_id,
            address_id=original_details.address_id,
            address_snapshot=original_details.address_snapshot,
            price_breakdown=json.dumps({
                "stitching": profile.blouse_price,
                "design": original.design.base_price,
            }),
            payment_status="payment_pending",
        ))
    notify(db, repeated.tailor_id, f"Repeated order #{repeated.id} is waiting for your response.", repeated.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.query(OrderSubmission).filter_by(
            customer_id=user["id"], idempotency_key=submission_key
        ).first()
        if prior:
            return redirect(f"/orders/{prior.order_id}")
        raise HTTPException(409, "The repeated order could not be saved.")
    return redirect(f"/orders/{repeated.id}")

@app.get("/designs")
def designs(db: Session = Depends(get_db)):
    return [{"id": d.id, "name": d.name, "description": d.description, "price": d.base_price} for d in db.query(Design).all()]
