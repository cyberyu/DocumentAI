import asyncio
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://surfsense:surfsense@surfsense-db-1:5432/surfsense")

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import select, Column, Integer, Text

class Base(DeclarativeBase):
    pass

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True)
    content = Column(Text)
    document_id = Column(Integer)

async def main():
    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        r = await session.execute(select(Chunk).where(Chunk.id.in_([11530, 11726, 11449])))
        chunks = r.scalars().all()
        for c in sorted(chunks, key=lambda x: x.id):
            print(f"=== CHUNK {c.id} (doc={c.document_id}) ===")
            print(c.content[:2000])
            print()

asyncio.run(main())
