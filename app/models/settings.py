"""Administrator-controlled settings that are not part of a business module.

`feature_flags` holds the central module On/Off switches (see
app/core/features.py). A missing row means ON, so the table never has to be
complete and an older database keeps its previous behaviour.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base


class FeatureFlag(Base):
    __tablename__ = "feature_flags"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(),
                                                 onupdate=func.now())
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
