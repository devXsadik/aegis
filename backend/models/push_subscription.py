"""A browser/phone that asked for alert notifications (Web Push) for one signed-in user."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from backend.db.database import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint = Column(Text, nullable=False, unique=True)     # the push service URL for this browser
    user_agent = Column(String(200), nullable=True)          # shown so the user knows which device
    created_at = Column(DateTime(timezone=True), server_default=func.now())
