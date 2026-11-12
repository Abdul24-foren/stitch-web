from io import BytesIO
from pathlib import Path

from PIL import Image

from app.config import MAX_UPLOAD_MB
from app.models import (
    CustomerAddress,
    Delivery,
    Design,
    Measurement,
    Notification,
    Order,
    OrderDetail,
    OrderStatusEvent,
    OrderSubmission,
    TailorProfile,
    User,
)


def register(client, name, email, role, password="correct-horse-battery"):
    return client.post(
        "/register",
        data={"name": name, "email": email, "role": role, "password": password},
        follow_redirects=False,
    )


def login(client, email, password="correct-horse-battery"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def add_address(client):
    return client.post(
        "/addresses",
        data={
            "label": "Home",
            "recipient_name": "Customer One",
            "phone": "5550100",
            "address_line": "1 Sample Street",
            "city": "Chennai",
            "postal_code": "600001",
            "make_default": "true",
        },
    )


def test_registration_role_protection_and_logout(app_client):
    client, _, _ = app_client

    invalid_role = client.post(
        "/register",
        data={
            "name": "Customer One",
            "email": "customer@example.com",
            "role": "admin",
            "password": "correct-horse-battery",
        },
    )
    assert invalid_role.status_code == 200
    assert "Choose a valid account type" in invalid_role.text

    response = register(client, "Customer One", "customer@example.com", "customer")
    assert response.status_code == 303
    assert client.get("/dashboard").status_code == 200
    assert client.get("/designs").json()
    assert client.post_without_csrf("/logout").status_code == 403
    assert client.post(
        "/tailor/profile",
        data={"shop_name": "No access", "location": "Chennai", "blouse_price": 500},
    ).status_code == 403

    assert client.post("/logout").status_code == 303
    assert client.get("/dashboard").status_code == 401
    assert login(client, "customer@example.com", "incorrect-password").status_code == 200
    assert client.get("/dashboard").status_code == 401
    assert login(client, "customer@example.com").status_code == 303


def test_registration_rejects_short_password(app_client):
    client, _, _ = app_client
    response = client.post(
        "/register",
        data={
            "name": "Customer One",
            "email": "customer@example.com",
            "role": "customer",
            "password": "short",
        },
    )
    assert response.status_code == 200
    assert "password 8–256 characters" in response.text
    assert client.get("/dashboard").status_code == 401


def test_measurement_profiles_are_validated_and_owned(app_client):
    client, session_factory, _ = app_client
    register(client, "Customer One", "customer@example.com", "customer")

    assert client.post("/measurements", data={"bust": "nan"}).status_code == 400
    assert client.post("/measurements", data={}).status_code == 400
    assert client.post(
        "/measurements",
        data={"label": "Tape checked", "bust": "92", "waist": "74", "shoulder": "38"},
    ).status_code == 303

    with session_factory() as db:
        assert db.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        measurement = db.query(Measurement).one()
        measurement_id = measurement.id

    client.post("/logout")
    register(client, "Customer Two", "other@example.com", "customer")
    client.post("/logout")
    register(client, "Studio One", "tailor@example.com", "tailor")
    with session_factory() as db:
        tailor = db.query(User).filter_by(email="tailor@example.com").one()
        design = db.query(Design).first()
        assert db.query(TailorProfile).filter_by(user_id=tailor.id).one()
        tailor_id, design_id = tailor.id, design.id

    client.post("/logout")
    login(client, "other@example.com")
    response = client.post(
        "/orders",
        data={
            "tailor_id": tailor_id,
            "design_id": design_id,
            "measurement_id": measurement_id,
            "submission_key": "wrong-owner-measurement-key",
        },
    )
    assert response.status_code == 400

    with session_factory() as db:
        assert db.query(Order).count() == 0


def test_order_idempotency_address_ownership_and_tailor_search(app_client):
    client, session_factory, _ = app_client
    register(client, "Customer One", "customer@example.com", "customer")
    add_address(client)
    with session_factory() as db:
        address_id = db.query(CustomerAddress).one().id
        design_id = db.query(Design).first().id

    client.post("/logout")
    register(client, "Studio One", "tailor@example.com", "tailor")
    assert client.post(
        "/tailor/profile",
        data={
            "shop_name": "Studio One",
            "location": "Chennai",
            "blouse_price": "600",
            "available": "true",
        },
    ).status_code == 303
    with session_factory() as db:
        tailor_id = db.query(User).filter_by(email="tailor@example.com").one().id

    directory = client.get("/tailors?search=Chennai&service=blouse")
    assert directory.status_code == 200
    assert "Studio One" in directory.text

    client.post("/logout")
    register(client, "Customer Two", "other@example.com", "customer")
    rejected = client.post(
        "/orders",
        data={
            "tailor_id": tailor_id,
            "design_id": design_id,
            "address_id": address_id,
            "submission_key": "foreign-address-key",
        },
    )
    assert rejected.status_code == 400
    with session_factory() as db:
        assert db.query(Order).count() == 0

    client.post("/logout")
    login(client, "customer@example.com")
    payload = {
        "tailor_id": tailor_id,
        "design_id": design_id,
        "address_id": address_id,
        "submission_key": "idempotent-order-key",
        "fabric_details": "Customer supplied silk",
        "notes": "Three-quarter sleeves",
    }
    created = client.post("/orders", data=payload)
    assert created.status_code == 303
    duplicated = client.post(
        "/orders",
        data={**payload, "tailor_id": 999, "design_id": 999, "address_id": 999},
    )
    assert duplicated.status_code == 303
    assert duplicated.headers["location"] == created.headers["location"]

    with session_factory() as db:
        assert db.query(Order).count() == 1
        assert db.query(OrderSubmission).count() == 1
        details = db.query(OrderDetail).one()
        assert details.fabric_details == "Customer supplied silk"
        order_id = db.query(Order).one().id

    client.post("/logout")
    login(client, "other@example.com")
    assert client.get(f"/orders/{order_id}").status_code == 404


def test_order_stitching_and_delivery_workflow_persists(app_client):
    client, session_factory, _ = app_client
    assert register(client, "Customer One", "customer@example.com", "customer").status_code == 303
    assert add_address(client).status_code == 303
    assert client.post(
        "/measurements",
        data={
            "label": "Tape checked",
            "bust": "92",
            "waist": "74",
            "shoulder": "38",
            "armhole": "42",
        },
    ).status_code == 303
    client.post("/logout")
    assert register(client, "Studio One", "tailor@example.com", "tailor").status_code == 303
    assert client.post(
        "/tailor/profile",
        data={
            "shop_name": "Studio One",
            "location": "Chennai",
            "bio": "Custom blouse tailoring",
            "blouse_price": "600",
            "available": "true",
        },
    ).status_code == 303

    with session_factory() as db:
        tailor = db.query(User).filter_by(email="tailor@example.com").one()
        design = db.query(Design).first()
        profile = db.query(TailorProfile).filter_by(user_id=tailor.id).one()
        tailor_id, design_id = tailor.id, design.id
        assert profile.blouse_price == 600
        measurement_id = db.query(Measurement).one().id
        address_id = db.query(CustomerAddress).one().id

    client.post("/logout")
    assert register(client, "Courier One", "courier@example.com", "delivery").status_code == 303
    client.post("/logout")
    login(client, "customer@example.com")
    order_response = client.post(
        "/orders",
        data={
            "tailor_id": tailor_id,
            "design_id": design_id,
            "measurement_id": measurement_id,
            "address_id": address_id,
            "submission_key": "workflow-order-key-1",
            "notes": "Three-quarter sleeves",
        },
    )
    assert order_response.status_code == 303, order_response.text

    with session_factory() as db:
        order = db.query(Order).one()
        delivery = db.query(Delivery).one()
        order_id, delivery_id = order.id, delivery.id
        address_id = db.query(CustomerAddress).one().id
        assert order.measurement_id == measurement_id
        assert order.status == "pending"
        assert order.amount == 600 + db.query(Design).filter_by(id=design_id).one().base_price

    client.post("/logout")
    login(client, "tailor@example.com")
    assert client.post(
        f"/orders/{order_id}/decision", data={"decision": "accepted"}
    ).status_code == 303
    assert "Bust: 92.0" in client.get("/dashboard").text
    assert client.post(
        f"/orders/{order_id}/status", data={"status": "stitching"}
    ).status_code == 400
    assert client.post(
        f"/orders/{order_id}/status", data={"status": "cutting"}
    ).status_code == 303
    assert client.post(
        f"/orders/{order_id}/status", data={"status": "stitching"}
    ).status_code == 303
    assert client.post(
        f"/orders/{order_id}/status", data={"status": "quality_check"}
    ).status_code == 303
    assert client.post(
        f"/orders/{order_id}/status", data={"status": "ready_for_pickup"}
    ).status_code == 303

    client.post("/logout")
    login(client, "courier@example.com")
    assert client.get("/dashboard").status_code == 200
    assert client.post(f"/deliveries/{delivery_id}/claim").status_code == 303
    assert client.post(
        f"/deliveries/{delivery_id}/status", data={"status": "arrived_at_tailor"}
    ).status_code == 303
    assert client.post(
        f"/deliveries/{delivery_id}/status", data={"status": "picked_up"}
    ).status_code == 303

    client.post("/logout")
    assert register(client, "Courier Two", "courier2@example.com", "delivery").status_code == 303
    assert client.post(
        f"/deliveries/{delivery_id}/status", data={"status": "delivered"}
    ).status_code == 404

    client.post("/logout")
    login(client, "courier@example.com")
    assert client.post(
        f"/deliveries/{delivery_id}/status", data={"status": "out_for_delivery"}
    ).status_code == 303
    assert client.post(
        f"/deliveries/{delivery_id}/status", data={"status": "arrived_at_customer"}
    ).status_code == 303
    assert client.post(
        f"/deliveries/{delivery_id}/status", data={"status": "delivered"}
    ).status_code == 303
    assert client.post(
        f"/deliveries/{delivery_id}/status", data={"status": "delivered"}
    ).status_code == 400

    with session_factory() as db:
        order = db.query(Order).one()
        delivery = db.query(Delivery).one()
        courier_id = db.query(User).filter_by(email="courier@example.com").one().id
        customer_id = db.query(User).filter_by(email="customer@example.com").one().id
        assert order.status == "delivered"
        assert delivery.partner_id == courier_id
        assert delivery.status == "delivered"
        assert [event.status for event in db.query(OrderStatusEvent).filter_by(
            order_id=order_id
        ).order_by(OrderStatusEvent.id)] == [
            "pending",
            "accepted",
            "cutting",
            "stitching",
            "quality_check",
            "ready_for_pickup",
            "out_for_delivery",
            "delivered",
        ]
        assert db.query(Notification).filter_by(recipient_id=customer_id).count() >= 7

    client.post("/logout")
    login(client, "customer@example.com")
    assert "delivered" in client.get("/dashboard").text
    assert client.post(f"/orders/{order_id}/confirm").status_code == 303
    with session_factory() as db:
        assert db.query(Order).one().status == "completed"
        assert db.query(OrderStatusEvent).filter_by(order_id=order_id).order_by(
            OrderStatusEvent.id
        ).all()[-1].status == "completed"


def test_delivery_cannot_claim_unready_order(app_client):
    client, session_factory, _ = app_client
    register(client, "Customer One", "customer@example.com", "customer")
    client.post("/logout")
    register(client, "Studio One", "tailor@example.com", "tailor")
    with session_factory() as db:
        tailor = db.query(User).filter_by(email="tailor@example.com").one()
        design = db.query(Design).first()
        tailor_id, design_id = tailor.id, design.id

    client.post("/logout")
    register(client, "Courier One", "courier@example.com", "delivery")
    client.post("/logout")
    login(client, "customer@example.com")
    add_address(client)
    with session_factory() as db:
        address_id = db.query(CustomerAddress).one().id
    client.post(
        "/orders",
        data={
            "tailor_id": tailor_id,
            "design_id": design_id,
            "address_id": address_id,
            "submission_key": "unready-order-key",
        },
    )
    with session_factory() as db:
        delivery_id = db.query(Delivery).one().id

    client.post("/logout")
    login(client, "courier@example.com")
    assert client.post(f"/deliveries/{delivery_id}/claim").status_code == 404
    assert "Order #" not in client.get("/dashboard").text


def test_tailor_rejection_persists_and_blocks_stitching(app_client):
    client, session_factory, _ = app_client
    register(client, "Customer One", "customer@example.com", "customer")
    client.post("/logout")
    register(client, "Studio One", "tailor@example.com", "tailor")
    with session_factory() as db:
        tailor_id = db.query(User).filter_by(email="tailor@example.com").one().id
        design_id = db.query(Design).first().id

    client.post("/logout")
    login(client, "customer@example.com")
    add_address(client)
    with session_factory() as db:
        address_id = db.query(CustomerAddress).one().id
    assert client.post(
        "/orders",
        data={
            "tailor_id": tailor_id,
            "design_id": design_id,
            "address_id": address_id,
            "submission_key": "reject-order-key",
        }
    ).status_code == 303
    with session_factory() as db:
        order_id = db.query(Order).one().id

    client.post("/logout")
    login(client, "tailor@example.com")
    assert client.post(
        f"/orders/{order_id}/decision",
        data={"decision": "rejected", "reason": "Unavailable fabric"},
    ).status_code == 303
    assert client.post(
        f"/orders/{order_id}/status", data={"status": "stitching"}
    ).status_code == 400
    with session_factory() as db:
        assert db.query(Order).one().status == "rejected"

    client.post("/logout")
    login(client, "customer@example.com")
    assert "rejected" in client.get("/dashboard").text


def test_reference_upload_validates_images_and_disclaims_ai(app_client):
    client, _, upload_dir = app_client
    image = BytesIO()
    Image.new("RGB", (2, 2), color="white").save(image, format="PNG")
    image_bytes = image.getvalue()

    assert client.post(
        "/upload-reference",
        files={"image": ("reference.png", image_bytes, "image/png")},
    ).status_code == 401
    assert register(client, "Customer One", "customer@example.com", "customer").status_code == 303
    assert client.post(
        "/upload-reference",
        files={"image": ("reference.txt", image_bytes, "text/plain")},
    ).status_code == 400
    assert client.post(
        "/upload-reference",
        files={"image": ("broken.png", b"not a PNG", "image/png")},
    ).status_code == 400
    assert client.post(
        "/upload-reference",
        files={
            "image": (
                "oversized.png",
                b"x" * (MAX_UPLOAD_MB * 1024 * 1024 + 1),
                "image/png",
            )
        },
    ).status_code == 413

    response = client.post(
        "/upload-reference",
        files={"image": ("reference.png", image_bytes, "image/png")},
    )
    assert response.status_code == 200
    assert "AI measurement is not performed" in response.json()["message"]
    assert Path(upload_dir / response.json()["file"]).is_file()
