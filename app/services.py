from sqlalchemy.orm import Session
from .models import Design

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
