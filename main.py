import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, condecimal, PositiveInt
from sqlalchemy import create_engine, Column, Integer, String, Numeric, Text, DateTime, ForeignKey, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.exc import IntegrityError
from datetime import datetime

# -----------------------------
# FastAPI app and CORS
# -----------------------------
app = FastAPI(title="Grocery Management API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Database (SQLite via SQLAlchemy)
# -----------------------------
DB_URL = os.getenv("SQL_DATABASE_URL", "sqlite:///./grocery.db")
engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class ProductORM(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False, index=True)
    category = Column(String(100), nullable=True, index=True)
    price = Column(Numeric(10, 2), nullable=False, default=0)
    stock = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    transactions = relationship("TransactionORM", back_populates="product", cascade="all, delete-orphan")

class TransactionORM(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(20), nullable=False)  # 'purchase' or 'sale'
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    product = relationship("ProductORM", back_populates="transactions")

Base.metadata.create_all(bind=engine)

# -----------------------------
# Schemas (Pydantic)
# -----------------------------
class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    category: Optional[str] = Field(None, max_length=100)
    price: condecimal(max_digits=10, decimal_places=2) = Field(0)
    stock: int = Field(0, ge=0)
    description: Optional[str] = None

class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    category: Optional[str] = Field(None, max_length=100)
    price: Optional[condecimal(max_digits=10, decimal_places=2)] = None
    stock: Optional[int] = Field(None, ge=0)
    description: Optional[str] = None

class ProductOut(BaseModel):
    id: int
    name: str
    category: Optional[str]
    price: condecimal(max_digits=10, decimal_places=2)
    stock: int
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class TransactionCreate(BaseModel):
    product_id: int
    type: str  # 'purchase' or 'sale'
    quantity: PositiveInt
    unit_price: condecimal(max_digits=10, decimal_places=2)
    note: Optional[str] = None

class TransactionOut(BaseModel):
    id: int
    product_id: int
    type: str
    quantity: int
    unit_price: condecimal(max_digits=10, decimal_places=2)
    note: Optional[str]
    created_at: datetime
    product_name: Optional[str] = None

    class Config:
        from_attributes = True

# -----------------------------
# Helpers
# -----------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------------
# Routes
# -----------------------------
@app.get("/")
def read_root():
    return {"message": "Grocery Management Backend running"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}

@app.get("/test")
def test_database():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"backend": "✅ Running", "sql": "✅ Connected", "db_url": DB_URL}
    except Exception as e:
        return {"backend": "✅ Running", "sql": f"❌ Error: {str(e)}", "db_url": DB_URL}

# Products CRUD
from fastapi import Depends
from sqlalchemy.orm import Session

@app.get("/api/products", response_model=List[ProductOut])
def list_products(db: Session = Depends(get_db)):
    items = db.query(ProductORM).order_by(ProductORM.created_at.desc()).all()
    return items

@app.post("/api/products", response_model=ProductOut)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    product = ProductORM(
        name=payload.name.strip(),
        category=(payload.category or None),
        price=payload.price,
        stock=payload.stock,
        description=payload.description,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(product)
    try:
        db.commit()
        db.refresh(product)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Product with this name already exists")
    return product

@app.put("/api/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    product = db.query(ProductORM).filter(ProductORM.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if payload.name is not None:
        product.name = payload.name.strip()
    if payload.category is not None:
        product.category = payload.category
    if payload.price is not None:
        product.price = payload.price
    if payload.stock is not None:
        product.stock = payload.stock
    if payload.description is not None:
        product.description = payload.description
    product.updated_at = datetime.utcnow()
    try:
        db.commit()
        db.refresh(product)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Product with this name already exists")
    return product

@app.delete("/api/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(ProductORM).filter(ProductORM.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()
    return {"status": "ok"}

# Transactions
@app.get("/api/transactions", response_model=List[TransactionOut])
def list_transactions(db: Session = Depends(get_db)):
    txs = db.query(TransactionORM).order_by(TransactionORM.created_at.desc()).all()
    # augment with product_name
    out: List[TransactionOut] = []
    for t in txs:
        out.append(TransactionOut(
            id=t.id,
            product_id=t.product_id,
            type=t.type,
            quantity=t.quantity,
            unit_price=t.unit_price,
            note=t.note,
            created_at=t.created_at,
            product_name=t.product.name if t.product else None,
        ))
    return out

@app.post("/api/transactions/purchase", response_model=TransactionOut)
def purchase(payload: TransactionCreate, db: Session = Depends(get_db)):
    if payload.type not in ("purchase", "sale"):
        raise HTTPException(status_code=400, detail="Invalid type. Use 'purchase' or 'sale'.")
    product = db.query(ProductORM).filter(ProductORM.id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    qty = int(payload.quantity)
    if payload.type == "sale" and product.stock < qty:
        raise HTTPException(status_code=400, detail="Insufficient stock for sale")

    # Adjust stock
    if payload.type == "purchase":
        product.stock += qty
    else:
        product.stock -= qty
    product.updated_at = datetime.utcnow()

    tx = TransactionORM(
        product_id=product.id,
        type=payload.type,
        quantity=qty,
        unit_price=payload.unit_price,
        note=payload.note,
        created_at=datetime.utcnow(),
    )
    db.add(tx)
    db.add(product)
    db.commit()
    db.refresh(tx)

    return TransactionOut(
        id=tx.id,
        product_id=tx.product_id,
        type=tx.type,
        quantity=tx.quantity,
        unit_price=tx.unit_price,
        note=tx.note,
        created_at=tx.created_at,
        product_name=product.name,
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
