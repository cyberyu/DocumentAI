"""Print the virtual XML for the MSFT document at a given offset range, same as the model sees."""
import asyncio, os, sys, json

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://surfsense:surfsense@surfsense-db-1:5432/surfsense")

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import select, Column, Integer, Text, String, JSON, Enum as SAEnum
import enum

class Base(DeclarativeBase):
    pass

class DocumentType(str, enum.Enum):
    FILE = "FILE"

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    document_type = Column(String)
    document_metadata = Column(JSON)
    search_space_id = Column(Integer)
    folder_id = Column(Integer)

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True)
    content = Column(Text)
    document_id = Column(Integer)

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # doc_id=10 is the latest re-ingested document
    DOC_ID = 10
    # The chunks that ARE in the retrieval matched set (from our debug_retrieval output)
    MATCHED = {11529, 11530, 11531, 11451, 11604, 11725, 11726}

    async with async_session() as session:
        r = await session.execute(
            select(Chunk.id, Chunk.content)
            .where(Chunk.document_id == DOC_ID)
            .order_by(Chunk.id)
        )
        chunks = r.all()

    print(f"Total chunks in doc {DOC_ID}: {len(chunks)}")

    # Build the XML line-by-line exactly as _build_document_xml does
    # so we can find what line numbers the equity statement and notes table are at
    lines = []
    metadata_lines = [
        "<document>",
        "<document_metadata>",
        f"  <document_id>{DOC_ID}</document_id>",
        "</document_metadata>",
        "",
    ]
    lines.extend(metadata_lines)

    chunk_entries = []
    for c in chunks:
        content = (c.content or "").strip()
        if not content:
            continue
        xml = f"  <chunk id='{c.id}'><![CDATA[{content}]]></chunk>"
        chunk_entries.append((c.id, xml))

    index_overhead = 1 + len(chunk_entries) + 1 + 1 + 1
    first_chunk_line = len(metadata_lines) + index_overhead + 1

    # Build index
    lines.append("<chunk_index>")
    current_line = first_chunk_line
    for cid, xml_str in chunk_entries:
        num_lines = xml_str.count("\n") + 1
        end_line = current_line + num_lines - 1
        matched_attr = ' matched="true"' if cid in MATCHED else ""
        lines.append(f'  <entry chunk_id="{cid}" lines="{current_line}-{end_line}"{matched_attr}/>')
        current_line = end_line + 1
    lines.append("</chunk_index>")
    lines.append("")
    lines.append("<document_content>")
    for _, xml_str in chunk_entries:
        lines.append(xml_str)
    lines.extend(["</document_content>", "</document>"])

    # Show what model sees at key offsets
    print(f"\nTotal lines in XML: {len(lines)}")
    print(f"First chunk content starts at line: {first_chunk_line}")

    # Find line numbers for key chunks
    for target_id in [11451, 11530]:
        for i, line in enumerate(lines, 1):
            if f"chunk id='{target_id}'" in line:
                print(f"\n=== Chunk {target_id} is at line {i} ===")
                print("\n".join(lines[max(0,i-2):i+5]))
                break

    # Show lines 315-340 (what model reads at offset=320)
    print("\n=== LINES 315-345 (model reads at offset=320) ===")
    for i, line in enumerate(lines[314:345], 315):
        marker = " <<< MATCHED" if any(f'chunk_id="{m}"' in line for m in MATCHED) else ""
        print(f"{i:4d}: {line[:120]}{marker}")

    # Show the chunk_index entries for MATCHED chunks
    print("\n=== CHUNK_INDEX entries for matched chunks ===")
    for i, line in enumerate(lines, 1):
        if 'matched="true"' in line:
            print(f"{i:4d}: {line}")

asyncio.run(main())
