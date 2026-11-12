from sqlalchemy.orm import Session
from .models import (
    Design,
    Notification,
    Order,
    OrderStatusEvent,
    TailorProfile,
    TailorService,
    User,
    utcnow,
)

DEFAULT_DESIGNS = [
    ("Classic Princess Cut", "A timeless fitted blouse with princess seams.", 650),
    ("High Neck Elegance", "A refined high-neck blouse for festive sarees.", 850),
    ("Boat Neck Minimal", "A clean boat neckline with a modern finish.", 600),
    ("Elbow Sleeve Traditional", "Traditional sleeve styling with a comfortable fit.", 700),
]

def seed_designs(db: Session):
    if db.query(Design).count() == 0:
        for name, description, price in DEFAULT_DESIGNS:
            db.add(Design(name=name, description=description, base_price=price))
        db.commit()


ORDER_TRANSITIONS = {
    "pending": {"accepted", "rejected", "cancelled"},
    "accepted": {"cutting", "cancelled"},
    "cutting": {"stitching"},
    "stitching": {"quality_check"},
    "quality_check": {"ready_for_pickup", "stitching"},
    "ready_for_pickup": {"out_for_delivery"},
    "out_for_delivery": {"delivered"},
    "delivered": {"completed"},
}


def transition_order(
    db: Session,
    order: Order,
    status: str,
    actor_id: int,
    note: str = "",
) -> None:
    if status not in ORDER_TRANSITIONS.get(order.status, set()):
        raise ValueError(f"Cannot transition order from {order.status} to {status}.")

    changed = db.query(Order).filter(
        Order.id == order.id,
        Order.status == order.status,
    ).update({"status": status}, synchronize_session=False)
    if changed != 1:
        raise ValueError("Order status changed concurrently; reload and try again.")

    order.status = status
    if order.order_details:
        order.order_details.updated_at = utcnow()
    details = f" ({note})" if note else ""
    db.add(
        OrderStatusEvent(
            order_id=order.id,
            status=status,
            actor_id=actor_id,
            note=note[:500],
        )
    )
    db.add(
        Notification(
            recipient_id=order.customer_id,
            order_id=order.id,
            message=f"Order #{order.id} is now {status.replace('_', ' ')}{details}.",
        )
    )
    if status not in {"accepted", "rejected"}:
        db.add(
            Notification(
                recipient_id=order.tailor_id,
                order_id=order.id,
                message=f"Order #{order.id} is now {status.replace('_', ' ')}{details}.",
            )
        )


def ensure_default_tailor_service(db: Session, tailor: User, profile: TailorProfile) -> None:
    if not db.query(TailorService).filter_by(tailor_id=tailor.id).first():
        db.add(
            TailorService(
                tailor_id=tailor.id,
                name="Saree blouse stitching",
                category="Saree blouse",
                price=profile.blouse_price,
            )
        )


def mark_notifications_read(db: Session, user_id: int) -> None:
    db.query(Notification).filter(
        Notification.recipient_id == user_id,
        Notification.read_at.is_(None),
    ).update({"read_at": utcnow()}, synchronize_session=False)
