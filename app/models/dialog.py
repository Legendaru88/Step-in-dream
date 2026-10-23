import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DialogRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class DialogLog(Base):
    __tablename__ = "dialog_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"), nullable=True)
    role: Mapped[DialogRole] = mapped_column(
        Enum(
            DialogRole,
            name="dialog_role",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="dialog_logs")
    goal = relationship("Goal", back_populates="dialog_logs")
