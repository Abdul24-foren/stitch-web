from pathlib import Path
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_
from email_validator import validate_email, EmailNotValidError
from .config import APP_NAME, SECRET_KEY, UPLOAD_DIR, MAX_UPLOAD_MB
from .database import Base, engine, get_db
from .models import User, TailorProfile, Design, Order, Delivery, Measurement
from .security import hash_password, verify_password, current_user
from .services import seed_designs

BASE = Path(__file__).resolve().parent
app = FastAPI(title=APP_NAME, version="1.0.0", description="Stitch It tailoring marketplace MVP")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        seed_designs(db)
    finally:
        db.close()

def page(request: Request, name: str, **context):
    return templates.TemplateResponse(request=request, name=name, context={"request": request, "user": current_user(request), **context})

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
             role: str = Form(...), phone: str = Form("")):
    name, email, role = name.strip(), email.strip().lower(), role.strip()
    if role not in {"customer", "tailor", "delivery"}:
        return page(request, "register.html", error="Choose a valid account type.")
    if len(name) < 2 or len(password) < 8:
        return page(request, "register.html", error="Name must be at least 2 characters and password at least 8 characters.")
    try:
        validate_email(email)
    except EmailNotValidError:
        return page(request, "register.html", error="Enter a valid email address.")
    db = next(get_db())
    try:
        if db.query(User).filter_by(email=email).first():
            return page(request, "register.html", error="An account with this email already exists.")
        user = User(name=name, email=email, password_hash=hash_password(password), role=role, phone=phone.strip())
        db.add(user); db.flush()
        if role == "tailor":
            db.add(TailorProfile(user_id=user.id, shop_name=f"{name}'s Studio", location="Chennai", blouse_price=500))
        db.commit()
        request.session["user"] = {"id": user.id, "name": user.name, "email": user.email, "role": user.role}
        return redirect("/dashboard")
    finally:
        db.close()

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return page(request, "login.html")

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    db = next(get_db())
    try:
        user = db.query(User).filter_by(email=email.strip().lower()).first()
        if not user or not verify_password(password, user.password_hash):
            return page(request, "login.html", error="Incorrect email or password.")
        request.session["user"] = {"id": user.id, "name": user.name, "email": user.email, "role": user.role}
        return redirect("/dashboard")
    finally:
        db.close()

@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request)
    role, uid = user["role"], user["id"]
    if role == "customer":
        orders = db.query(Order).filter_by(customer_id=uid).order_by(Order.created_at.desc()).all()
        return page(request, "customer_dashboard.html", orders=orders, designs=db.query(Design).all(),
                    tailors=db.query(TailorProfile).filter_by(available=1).all())
    if role == "tailor":
        orders = db.query(Order).filter_by(tailor_id=uid).order_by(Order.created_at.desc()).all()
        profile = db.query(TailorProfile).filter_by(user_id=uid).first()
        return page(request, "tailor_dashboard.html", orders=orders, profile=profile)
    deliveries = db.query(Delivery).filter(or_(Delivery.partner_id == uid, Delivery.partner_id.is_(None))).all()
    return page(request, "delivery_dashboard.html", deliveries=deliveries)

@app.post("/tailor/profile")
def update_profile(request: Request, shop_name: str = Form(...), location: str = Form(...),
                   bio: str = Form(""), blouse_price: float = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, "tailor")
    if blouse_price < 0:
        raise HTTPException(400, "Price cannot be negative.")
    profile = db.query(TailorProfile).filter_by(user_id=user["id"]).first()
    profile.shop_name, profile.location, profile.bio, profile.blouse_price = shop_name[:140], location[:180], bio[:2000], blouse_price
    db.commit()
    return redirect("/dashboard")

@app.post("/orders")
def create_order(request: Request, tailor_id: int = Form(...), design_id: int = Form(...),
                 notes: str = Form(""), db: Session = Depends(get_db)):
    user = require_user(request, "customer")
    tailor = db.query(User).filter_by(id=tailor_id, role="tailor").first()
    profile = db.query(TailorProfile).filter_by(user_id=tailor_id, available=1).first()
    design = db.query(Design).filter_by(id=design_id).first()
    if not tailor or not profile or not design:
        raise HTTPException(400, "Select a valid tailor and design.")
    order = Order(customer_id=user["id"], tailor_id=tailor_id, design_id=design_id,
                  notes=notes[:3000], amount=float(profile.blouse_price + design.base_price))
    db.add(order); db.flush()
    db.add(Delivery(order_id=order.id))
    db.commit()
    return redirect("/dashboard")

@app.post("/orders/{order_id}/decision")
def order_decision(order_id: int, request: Request, decision: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, "tailor")
    order = db.query(Order).filter_by(id=order_id, tailor_id=user["id"]).first()
    if not order or order.status != "pending":
        raise HTTPException(404, "Pending order not found.")
    if decision not in {"accepted", "rejected"}:
        raise HTTPException(400, "Invalid decision.")
    order.status = decision
    db.commit()
    return redirect("/dashboard")

@app.post("/orders/{order_id}/status")
def order_status(order_id: int, request: Request, status: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, "tailor")
    allowed = {"stitching", "ready_for_pickup"}
    order = db.query(Order).filter_by(id=order_id, tailor_id=user["id"]).first()
    if not order or status not in allowed or order.status not in {"accepted", "stitching"}:
        raise HTTPException(400, "Invalid order status transition.")
    order.status = status
    db.commit()
    return redirect("/dashboard")

@app.post("/deliveries/{delivery_id}/claim")
def claim_delivery(delivery_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, "delivery")
    delivery = db.query(Delivery).filter_by(id=delivery_id, partner_id=None).first()
    if not delivery or delivery.order.status != "ready_for_pickup":
        raise HTTPException(404, "Available delivery not found.")
    delivery.partner_id, delivery.status = user["id"], "assigned"
    db.commit()
    return redirect("/dashboard")

@app.post("/deliveries/{delivery_id}/status")
def delivery_status(delivery_id: int, request: Request, status: str = Form(...), db: Session = Depends(get_db)):
    user = require_user(request, "delivery")
    delivery = db.query(Delivery).filter_by(id=delivery_id, partner_id=user["id"]).first()
    if not delivery or status not in {"picked_up", "delivered"}:
        raise HTTPException(404, "Delivery not found.")
    if status == "picked_up" and delivery.order.status != "ready_for_pickup":
        raise HTTPException(400, "Garment is not ready for pickup.")
    if status == "delivered" and delivery.status != "picked_up":
        raise HTTPException(400, "Pick up the garment before delivery.")
    delivery.status = status
    if status == "delivered":
        delivery.order.status = "delivered"
    db.commit()
    return redirect("/dashboard")

@app.post("/measurements")
def save_measurements(request: Request, label: str = Form("My measurements"), notes: str = Form(""),
                      bust: float | None = Form(None), waist: float | None = Form(None),
                      shoulder: float | None = Form(None), armhole: float | None = Form(None),
                      db: Session = Depends(get_db)):
    user = require_user(request, "customer")
    values = [v for v in (bust, waist, shoulder, armhole) if v is not None]
    if any(v <= 0 or v > 250 for v in values):
        raise HTTPException(400, "Measurements must be between 0 and 250 cm.")
    db.add(Measurement(customer_id=user["id"], label=label[:100], notes=notes[:2000],
                       bust=bust, waist=waist, shoulder=shoulder, armhole=armhole))
    db.commit()
    return redirect("/dashboard")

@app.post("/upload-reference")
async def upload_reference(request: Request, image: UploadFile = File(...)):
    require_user(request, "customer")
    if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(400, "Only JPG, PNG or WebP images are accepted.")
    content = await image.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, "Image exceeds upload size limit.")
    # Verify actual image content, not just the browser-provided MIME type.
    from PIL import Image
    from io import BytesIO
    try:
        with Image.open(BytesIO(content)) as img:
            img.verify()
    except Exception:
        raise HTTPException(400, "The uploaded file is not a valid image.")
    import uuid
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[image.content_type]
    filename = f"{uuid.uuid4().hex}{suffix}"
    (UPLOAD_DIR / filename).write_bytes(content)
    return JSONResponse({"message": "Reference image uploaded. AI measurement is not performed by this MVP.", "file": filename})

@app.get("/designs")
def designs(db: Session = Depends(get_db)):
    return [{"id": d.id, "name": d.name, "description": d.description, "price": d.base_price} for d in db.query(Design).all()]
