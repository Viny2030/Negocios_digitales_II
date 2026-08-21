"""
Modelos SQLAlchemy — capa de persistencia del worker diario.

Dos tablas, calcadas del modelo conceptual del diseño original:

    dim_channels               -> TrackedChannel  (qué canales seguimos)
    fact_channel_metrics_daily -> ChannelMetricSnapshot (una fila por canal/día)

Un canal trackeado nunca se borra físicamente (soft delete vía `active`) para
no perder el histórico de snapshots ya tomados. `ChannelMetricSnapshot` tiene
una unique constraint (tracked_channel_id, snapshot_date) que hace el job
diario idempotente: correrlo dos veces el mismo día no duplica filas.
"""
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Boolean,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TrackedChannel(Base):
    """Un canal que el worker diario debe snapshotear (dim_channels)."""

    __tablename__ = "tracked_channels"
    __table_args__ = (UniqueConstraint("platform", "native_id", name="uq_platform_native_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    native_id: Mapped[str] = mapped_column(String(200), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(200), nullable=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    snapshots: Mapped[list["ChannelMetricSnapshot"]] = relationship(
        back_populates="tracked_channel", cascade="all, delete-orphan", order_by="ChannelMetricSnapshot.snapshot_date"
    )

    @property
    def universal_id(self) -> str:
        return f"{self.platform}:{self.native_id}"


class ChannelMetricSnapshot(Base):
    """Una foto de las métricas de un canal en un día dado (fact_channel_metrics_daily)."""

    __tablename__ = "channel_metric_snapshots"
    __table_args__ = (UniqueConstraint("tracked_channel_id", "snapshot_date", name="uq_channel_snapshot_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tracked_channel_id: Mapped[int] = mapped_column(ForeignKey("tracked_channels.id"), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)

    followers: Mapped[int] = mapped_column(Integer, default=0)
    total_views: Mapped[int] = mapped_column(Integer, default=0)
    total_posts: Mapped[int] = mapped_column(Integer, default=0)
    raw_interactions: Mapped[int] = mapped_column(Integer, default=0)
    normalized_er: Mapped[float] = mapped_column(Float, default=0.0)
    tier: Mapped[str] = mapped_column(String(20), default="nano")

    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    tracked_channel: Mapped["TrackedChannel"] = relationship(back_populates="snapshots")
