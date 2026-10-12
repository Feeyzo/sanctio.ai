"""Creates tables and demo data (a sample online store with customers and orders)."""
from sqlalchemy.orm import Session

from .config import ADMIN_EMAIL, ADMIN_PASSWORD, DEMO_API_KEY
from .db import Base, engine
from .models import AdminUser, Business, Customer, Order
from .security import hash_password, sha256
from .tools import REGISTRY

CUSTOMERS = [
    ("C-1001", "Amina Yusuf", "amina@example.com", "08030000001"),
    ("C-1002", "Chinedu Okafor", "chinedu@example.com", "08030000002"),
    ("C-1003", "Fatima Bello", "fatima@example.com", "08030000003"),
]
ORDERS = [  # ref, customer index, item, amount, status, payment, expected delivery
    ("ORD-10021", 0, "Infinix Hot 40 smartphone", 185000, "processing", "paid", "2026-10-14"),
    ("ORD-10022", 0, "Wireless earbuds", 18500, "delivered", "paid", "2026-10-02"),
    ("ORD-10023", 0, "Men's Ankara shirt", 12000, "pending", "paid", "2026-10-16"),
    ("ORD-10031", 1, "HP 15 laptop", 520000, "shipped", "paid", "2026-10-11"),
    ("ORD-10032", 1, "Rice cooker", 32000, "delivered", "paid", "2026-09-28"),
    ("ORD-10041", 2, "Office chair", 95000, "delivered", "paid", "2026-10-01"),
    ("ORD-10042", 2, "Bluetooth speaker", 27000, "processing", "paid", "2026-10-13"),
]
ADDRESSES = ["15 Zoo Road, Nassarawa, Kano", "7 Allen Avenue, Ikeja, Lagos", "22 Ahmadu Bello Way, Kaduna"]


def init_db(db: Session):
    Base.metadata.create_all(engine)
    if db.query(Business).first():
        return
    biz = Business(name="ShopWise NG", api_key_hash=sha256(DEMO_API_KEY), allowed_actions=",".join(REGISTRY))
    db.add(biz)
    db.flush()
    customers = []
    for ext, name, email, phone in CUSTOMERS:
        c = Customer(business_id=biz.id, external_id=ext, name=name, email=email, phone=phone)
        db.add(c)
        customers.append(c)
    db.flush()
    for ref, ci, item, amount, status, pay, eta in ORDERS:
        db.add(Order(order_ref=ref, customer_id=customers[ci].id, item=item, amount=amount, status=status,
                     payment_status=pay, shipping_address=ADDRESSES[ci], expected_delivery=eta))
    db.add(AdminUser(business_id=biz.id, email=ADMIN_EMAIL, password_hash=hash_password(ADMIN_PASSWORD),
                     name="Support Admin"))
    db.commit()
