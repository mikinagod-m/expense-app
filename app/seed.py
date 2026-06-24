"""Create tables and a few demo rows so you can click around immediately.

Run:  python -m app.seed
"""
import datetime as dt

from .db import engine, SessionLocal
from .models import Base, User, Period, ClaimType


def run():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.query(User).count() == 0:
            mgr = User(name="Morgan Hale", email="morgan.hale@example.com",
                       is_finance=True)
            db.add(mgr)
            db.flush()
            db.add_all([
                User(name="Jordan Blake", email="jordan.blake@example.com",
                     manager_id=mgr.id, has_credit_card=True),
                User(name="Riley Stone", email="riley.stone@example.com",
                     manager_id=mgr.id, has_credit_card=True),
            ])
        if db.query(Period).count() == 0:
            today = dt.date.today()
            db.add_all([
                Period(year=today.year, month=today.month, type=ClaimType.cash,
                       deadline=today + dt.timedelta(days=10), is_open=True),
                Period(year=today.year, month=today.month, type=ClaimType.card,
                       deadline=today + dt.timedelta(days=10), is_open=True),
            ])
        db.commit()
    print("Seeded. Start with: uvicorn app.main:app --reload --port 8000")


if __name__ == "__main__":
    run()
