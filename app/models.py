from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Boolean,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    tailor_profile: Mapped["TailorProfile"] = relationship(back_populates="user", uselist=False)
    tailor_services: Mapped[list["TailorService"]] = relationship(
        back_populates="tailor"
    )

class TailorProfile(Base):
    __tablename__ = "tailor_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    shop_name: Mapped[str] = mapped_column(String(140), default="")
    location: Mapped[str] = mapped_column(String(180), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    blouse_price: Mapped[float] = mapped_column(Float, default=500)
    available: Mapped[int] = mapped_column(Integer, default=1)
    user: Mapped[User] = relationship(back_populates="tailor_profile")

class Design(Base):
    __tablename__ = "designs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(60), default="Saree blouse")
    base_price: Mapped[float] = mapped_column(Float, default=500)

class Measurement(Base):
    __tablename__ = "measurements"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(100), default="My measurements")
    notes: Mapped[str] = mapped_column(Text, default="")
    bust: Mapped[float | None] = mapped_column(Float, nullable=True)
    waist: Mapped[float | None] = mapped_column(Float, nullable=True)
    shoulder: Mapped[float | None] = mapped_column(Float, nullable=True)
    armhole: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tailor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    design_id: Mapped[int] = mapped_column(ForeignKey("designs.id"))
    measurement_id: Mapped[int | None] = mapped_column(ForeignKey("measurements.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    customer = relationship("User", foreign_keys=[customer_id])
    tailor = relationship("User", foreign_keys=[tailor_id])
    design = relationship("Design")
    measurement = relationship("Measurement")
    order_details = relationship("OrderDetail", back_populates="order", uselist=False)

class Delivery(Base):
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="unassigned")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    order = relationship("Order")
    partner = relationship("User")


class CustomerAddress(Base):
    __tablename__ = "customer_addresses"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(60), default="Home")
    recipient_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(30))
    address_line: Mapped[str] = mapped_column(String(300))
    city: Mapped[str] = mapped_column(String(120))
    postal_code: Mapped[str] = mapped_column(String(20), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TailorBusinessProfile(Base):
    __tablename__ = "tailor_business_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    shop_address: Mapped[str] = mapped_column(String(300), default="")
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    working_hours: Mapped[str] = mapped_column(String(200), default="")


class DeliveryPartnerProfile(Base):
    __tablename__ = "delivery_partner_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    available: Mapped[bool] = mapped_column(Boolean, default=True)


class TailorService(Base):
    __tablename__ = "tailor_services"
    id: Mapped[int] = mapped_column(primary_key=True)
    tailor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80), default="Saree blouse")
    price: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    tailor = relationship("User", back_populates="tailor_services")


class ReferenceImage(Base):
    __tablename__ = "reference_images"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(80), unique=True)
    content_type: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OrderDetail(Base):
    __tablename__ = "order_details"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), unique=True
    )
    order_reference: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    garment_type: Mapped[str] = mapped_column(String(100), default="Saree blouse")
    fabric_details: Mapped[str] = mapped_column(String(1000), default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    measurement_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    reference_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("reference_images.id"), nullable=True
    )
    address_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_addresses.id"), nullable=True
    )
    payment_status: Mapped[str] = mapped_column(
        String(30), default="not_configured"
    )
    address_snapshot: Mapped[str] = mapped_column(Text, default="{}")
    price_breakdown: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    order = relationship("Order", back_populates="order_details")
    reference_image = relationship("ReferenceImage")
    address = relationship("CustomerAddress")


class OrderSubmission(Base):
    __tablename__ = "order_submissions"
    __table_args__ = (
        UniqueConstraint("customer_id", "idempotency_key", name="uq_order_submission_key"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OrderStatusEvent(Base):
    __tablename__ = "order_status_events"
    __table_args__ = (Index("ix_order_status_events_order_created", "order_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor = relationship("User")


class DeliveryStatusEvent(Base):
    __tablename__ = "delivery_status_events"
    __table_args__ = (Index("ix_delivery_events_delivery_created", "delivery_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(
        ForeignKey("deliveries.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    actor = relationship("User")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_recipient_created", "recipient_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=True
    )
    message: Mapped[str] = mapped_column(String(500))
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
