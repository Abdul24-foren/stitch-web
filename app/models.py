from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    tailor_profile: Mapped["TailorProfile"] = relationship(back_populates="user", uselist=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    customer = relationship("User", foreign_keys=[customer_id])
    tailor = relationship("User", foreign_keys=[tailor_id])
    design = relationship("Design")

class Delivery(Base):
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="unassigned")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    order = relationship("Order")
    partner = relationship("User")
