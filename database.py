"""
Database Layer: SQLAlchemy-based SQLite initialization and ORM models.
Provides Product and Order table definitions with automatic seeding.
"""

import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session


# Configuration & Initialization


DATABASE_URL: str = "sqlite:///retail.db"
Base = declarative_base()



# ORM Models


class Product(Base):
    """
    Product model representing inventory SKUs in the retail catalog.
    
    Attributes:
        product_id: Unique identifier (Primary Key)
        product_name: Display name, must be unique
        brand: Manufacturer/brand name
        unit_price_inr: Price in Indian Rupees (Float)
        stock_qty: Available quantity in inventory
    """
    __tablename__ = "products"

    product_id: str = Column(String(50), primary_key=True, index=True)
    product_name: str = Column(String(255), unique=True, nullable=False, index=True)
    brand: str = Column(String(100), nullable=False)
    unit_price_inr: float = Column(Float, nullable=False)
    stock_qty: int = Column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return (
            f"<Product(id={self.product_id}, name={self.product_name}, "
            f"price={self.unit_price_inr}, stock={self.stock_qty})>"
        )


class Order(Base):
    """
    Order model representing finalized B2B transactions.
    
    Attributes:
        order_id: Unique transaction identifier (UUID format)
        customer_name: Customer/buyer identifier
        items_json: Serialized JSON array of ordered items
        total_amount: Final invoice amount including GST in INR
        created_at: Timestamp of transaction creation
    """
    __tablename__ = "orders"

    order_id: str = Column(String(36), primary_key=True, index=True)
    customer_name: str = Column(String(255), nullable=False)
    items_json: str = Column(Text, nullable=False)
    total_amount: float = Column(Float, nullable=False)
    created_at: datetime = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<Order(id={self.order_id}, customer={self.customer_name}, "
            f"total={self.total_amount}, created={self.created_at})>"
        )



# Database Engine & Session Factory


def get_engine():
    """Create and return SQLAlchemy engine instance."""
    return create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )


def get_session_factory(engine):
    """Create and return SessionLocal factory for database sessions."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)



# Initialization & Seeding


SEED_PRODUCTS: List[Dict[str, Any]] = [
    {
        "product_id": "PROD_001",
        "product_name": "Aashirvaad Atta",
        "brand": "ITC",
        "unit_price_inr": 450.00,
        "stock_qty": 100,
    },
    {
        "product_id": "PROD_002",
        "product_name": "Amul Butter",
        "brand": "Amul",
        "unit_price_inr": 105.00,
        "stock_qty": 200,
    },
    {
        "product_id": "PROD_003",
        "product_name": "Surf Excel",
        "brand": "HUL",
        "unit_price_inr": 160.00,
        "stock_qty": 150,
    },
    {
        "product_id": "PROD_004",
        "product_name": "Tata Salt",
        "brand": "Tata",
        "unit_price_inr": 28.00,
        "stock_qty": 500,
    },
    {
        "product_id": "PROD_005",
        "product_name": "Maggi Noodles",
        "brand": "Nestle",
        "unit_price_inr": 14.00,
        "stock_qty": 1000,
    },
]


def initialize_database() -> None:
    """
    Initialize SQLite database: create all tables and seed default products.
    Idempotent operation - safe to call multiple times.
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    
    SessionLocal = get_session_factory(engine)
    session: Session = SessionLocal()
    
    try:
        # Check if products table is empty
        product_count: int = session.query(Product).count()
        
        if product_count == 0:
            print("[DB] Seeding default products...")
            for product_data in SEED_PRODUCTS:
                product = Product(**product_data)
                session.add(product)
                print(f"   Added: {product.product_name}")
            
            session.commit()
            print(f"[DB] Successfully seeded {len(SEED_PRODUCTS)} products.\n")
        else:
            print(f"[DB] Products table already populated ({product_count} items). Skipping seed.\n")
    
    except Exception as e:
        session.rollback()
        print(f"[DB] ERROR during seeding: {str(e)}")
        raise
    
    finally:
        session.close()


def get_product_by_name(
    session: Session, 
    product_name: str
) -> Optional[Product]:
    """
    Query product by name with case-insensitive matching.
    
    Args:
        session: Active SQLAlchemy database session
        product_name: Product name to search for
        
    Returns:
        Product instance if found, None otherwise
    """
    from sqlalchemy import func
    
    product: Optional[Product] = session.query(Product).filter(
        func.lower(Product.product_name) == func.lower(product_name)
    ).first()
    
    return product


def get_all_products(session: Session) -> List[Product]:
    """Retrieve all products from inventory."""
    return session.query(Product).all()
