import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StepStatus(str, enum.Enum):
    PENDING = "pending"
    DONE = "done"
    SKIPPED = "skipped"


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column("order", Integer, nullable=False)
    status: Mapped[StepStatus] = mapped_column(
        Enum(
            StepStatus,
            name="step_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=StepStatus.PENDING,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    goal = relationship("Goal", back_populates="steps")
