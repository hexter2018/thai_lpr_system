from sqlalchemy import Column, Integer, String, Float, Enum
from sqlalchemy.ext.declarative import declarative_base


Base = declarative_base()


class PlateRecord(Base):
__tablename__ = "plates"
id = Column(Integer, primary_key=True, index=True)
full_plate = Column(String)
province = Column(String, default="")
confidence = Column(Float)
type = Column(Enum("ALPR", "MLPR"))
image_path = Column(String)




# Directory: alpr_backend/database/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base
import os


POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://user:password@localhost/alpr")
engine = create_engine(POSTGRES_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# Auto-create tables
Base.metadata.create_all(bind=engine)