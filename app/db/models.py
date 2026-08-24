"""
Modelos SQLAlchemy — capa de persistencia del worker diario.

Tres tablas, calcadas del modelo conceptual del diseño original más el
catálogo de tipos de canal agregado después:

    dim_channels               -> TrackedChannel  (qué canales seguimos)
    fact_channel_metrics_daily -> ChannelMetricSnapshot (una fila por canal/día)
    channel_types              -> ChannelType (taxonomía propia + categorías de YouTube)

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


class ChannelType(Base):
    """
    Tipo/categoría de canal para el catálogo (pestaña "Catálogo" del
    dashboard) — pensado para ser flexible: arranca sembrado con las 15
    categorías nativas de YouTube (`is_custom=False`, ver
    `services/collectors/youtube.py::DISCOVER_CATEGORY_LABELS`) y se le
    pueden sumar tipos propios de negocio en cualquier momento
    (`is_custom=True`, vía `POST /api/v1/catalog/types`) sin tocar código
    ni redesplegar nada.
    """

    __tablename__ = "channel_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(140), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # False = sembrado automáticamente desde una categoría de YouTube;
    # True = creado a mano por el usuario (tipo de negocio propio).
    is_custom: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    tracked_channels: Mapped[list["TrackedChannel"]] = relationship(back_populates="channel_type")


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
    # Tipo de canal para el catálogo (opcional: un canal puede quedar sin
    # clasificar). Nullable a propósito para no romper canales ya
    # trackeados antes de agregar este campo (ver migración liviana en
    # `db/session.py::init_db`).
    channel_type_id: Mapped[int | None] = mapped_column(ForeignKey("channel_types.id"), nullable=True)

    snapshots: Mapped[list["ChannelMetricSnapshot"]] = relationship(
        back_populates="tracked_channel", cascade="all, delete-orphan", order_by="ChannelMetricSnapshot.snapshot_date"
    )
    channel_type: Mapped["ChannelType | None"] = relationship(back_populates="tracked_channels")

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


class User(Base):
    """
    Cuenta de usuario (auth armada desde cero: email + contraseña con hash
    bcrypt) y su plan de suscripción (`app.models.domain.Plan`).

    No hay pasarela de pago real conectada todavía (Mercado Pago/Stripe) —
    proyecto universitario: `plan`/`plan_active_until`/`report_credits` se
    actualizan a mano vía `POST /api/v1/auth/admin/set-plan`, dejando la
    arquitectura lista para conectar un cobro real más adelante sin tocar
    el resto del sistema (ver `app/services/users.py` y `app/api/deps.py`).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    # Vigencia de 'mensual'/'premium' (None = nunca activado o vencido). No
    # aplica a 'unica', que en cambio consume `report_credits`.
    plan_active_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Saldo de reportes puntuales comprados bajo el plan 'unica'.
    report_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    @property
    def has_active_subscription(self) -> bool:
        """True si el plan es 'mensual'/'premium' y no venció `plan_active_until`."""
        if self.plan not in ("mensual", "premium"):
            return False
        if self.plan_active_until is None:
            return False
        return self.plan_active_until >= datetime.utcnow()

    @property
    def has_full_stats_access(self) -> bool:
        """
        Acceso a "toda la estadística": suscripción activa, o plan 'unica'
        con al menos 1 crédito de reporte disponible todavía sin consumir.
        """
        return self.has_active_subscription or (self.plan == "unica" and self.report_credits > 0)

    @property
    def has_premium_access(self) -> bool:
        """Proyecciones + recomendaciones: requiere 'premium' activo (no alcanza con 'unica')."""
        return self.plan == "premium" and self.has_active_subscription
