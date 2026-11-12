from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    sku: Mapped[str] = mapped_column(String(40), primary_key=True)
    name_he: Mapped[str] = mapped_column(String(200))
    name_en: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(30), index=True)
    unit: Mapped[str] = mapped_column(String(20))
    price: Mapped[float] = mapped_column(Float)
    meal_type: Mapped[str] = mapped_column(String(10), index=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    serves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description_he: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )
