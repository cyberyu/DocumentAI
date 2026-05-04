"""
Migration script: PostgreSQL pgvector → OpenSearch

Migrates existing chunk embeddings from PostgreSQL to OpenSearch.
Run this once after deploying the new OpenSearch storage layer.

Usage:
    docker-compose -f docker-compose-adaptable-rag.yml exec backend python migrate_postgres_to_opensearch.py

Or mount and run locally:
    python migrate_postgres_to_opensearch.py
"""
import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import List

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def migrate_chunks():
    """
    Migrate all chunks from PostgreSQL pgvector to OpenSearch.
    
    Process:
    1. Get all distinct search spaces from PostgreSQL
    2. For each search space:
       a. Fetch all chunks with embeddings
       b. Create OpenSearch index
       c. Bulk index chunks
    3. Verify migration success
    """
    try:
        # Import after path setup
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        from app.db import Chunk, Document, get_async_session
        from app.storage.opensearch_chunk_storage import OpenSearchChunkStorage

        # Get OpenSearch configuration from environment
        opensearch_hosts = os.getenv("OPENSEARCH_HOSTS", "http://localhost:9200").split(
            ","
        )
        index_prefix = os.getenv("OPENSEARCH_INDEX_PREFIX", "surfsense")

        logger.info(f"Connecting to OpenSearch: {opensearch_hosts}")
        opensearch = OpenSearchChunkStorage(
            hosts=opensearch_hosts, index_prefix=index_prefix
        )

        # Get database session
        async for session in get_async_session():
            logger.info("Connected to PostgreSQL database")

            # Get all unique search spaces
            result = await session.execute(
                select(Document.search_space_id).distinct()
            )
            search_space_ids = [row[0] for row in result.all()]

            logger.info(f"Found {len(search_space_ids)} search spaces to migrate")

            total_migrated = 0
            total_failed = 0

            # Migrate each search space
            for space_id in search_space_ids:
                logger.info(f"\n{'=' * 80}")
                logger.info(f"Migrating search space {space_id}...")
                logger.info(f"{'=' * 80}")

                # Get all chunks for this search space with document metadata
                query = (
                    select(Chunk)
                    .options(joinedload(Chunk.document))
                    .join(Document, Chunk.document_id == Document.id)
                    .where(Document.search_space_id == space_id)
                    .order_by(Chunk.id)
                )

                result = await session.execute(query)
                chunks = result.scalars().unique().all()

                if not chunks:
                    logger.warning(f"  No chunks found for search space {space_id}")
                    continue

                logger.info(f"  Found {len(chunks)} chunks to migrate")

                # Determine embedding dimensions from first chunk
                embedding_dim = len(chunks[0].embedding) if chunks else 384
                logger.info(f"  Embedding dimensions: {embedding_dim}")

                # Create OpenSearch index
                try:
                    await opensearch.create_index(space_id, embedding_dim)
                    logger.info(f"  ✓ Created/verified OpenSearch index")
                except Exception as e:
                    logger.error(f"  ✗ Failed to create index: {e}")
                    continue

                # Prepare chunks for bulk indexing
                chunk_docs = []
                for chunk in chunks:
                    try:
                        # Validate embedding
                        if not chunk.embedding or len(chunk.embedding) == 0:
                            logger.warning(
                                f"    Skipping chunk {chunk.id}: no embedding"
                            )
                            continue

                        chunk_doc = {
                            "chunk_id": str(chunk.id),
                            "document_id": str(chunk.document_id),
                            "content": chunk.content or "",
                            "embedding": chunk.embedding,
                            "metadata": {
                                "token_count": getattr(chunk, "token_count", None),
                                "prefix_context": getattr(chunk, "prefix_context", None),
                                "chunk_index": getattr(chunk, "chunk_index", None),
                            },
                            "indexed_at": (
                                chunk.created_at.isoformat()
                                if hasattr(chunk, "created_at") and chunk.created_at
                                else datetime.utcnow().isoformat()
                            ),
                        }
                        chunk_docs.append(chunk_doc)
                    except Exception as e:
                        logger.error(f"    Error preparing chunk {chunk.id}: {e}")
                        total_failed += 1

                if not chunk_docs:
                    logger.warning(f"  No valid chunks to index")
                    continue

                # Bulk index to OpenSearch
                logger.info(f"  Indexing {len(chunk_docs)} chunks...")
                try:
                    success, failed = await opensearch.index_chunks(
                        chunk_docs, space_id, batch_size=100
                    )

                    total_migrated += success
                    total_failed += failed

                    logger.info(f"  ✓ Indexed {success} chunks")
                    if failed > 0:
                        logger.warning(f"  ⚠ Failed to index {failed} chunks")

                    # Verify index statistics
                    stats = await opensearch.get_index_stats(space_id)
                    logger.info(
                        f"  Index stats: {stats.get('document_count', 0)} documents, "
                        f"{stats.get('store_size_bytes', 0) / 1024 / 1024:.2f} MB"
                    )

                except Exception as e:
                    logger.error(f"  ✗ Bulk indexing failed: {e}")
                    total_failed += len(chunk_docs)

            # Final summary
            logger.info(f"\n{'=' * 80}")
            logger.info("MIGRATION COMPLETE")
            logger.info(f"{'=' * 80}")
            logger.info(f"Total chunks migrated: {total_migrated}")
            logger.info(f"Total chunks failed: {total_failed}")

            if total_failed > 0:
                logger.warning(
                    f"⚠ {total_failed} chunks failed to migrate. Check logs above."
                )
                return False
            else:
                logger.info("✓ All chunks migrated successfully!")
                return True

    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error(
            "Make sure you're running this script from the backend container "
            "or have the necessary dependencies installed."
        )
        return False
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return False


async def verify_migration():
    """
    Verify migration by comparing PostgreSQL and OpenSearch counts.
    """
    try:
        from sqlalchemy import func, select

        from app.db import Chunk, Document, get_async_session
        from app.storage.opensearch_chunk_storage import OpenSearchChunkStorage

        opensearch_hosts = os.getenv("OPENSEARCH_HOSTS", "http://localhost:9200").split(
            ","
        )
        index_prefix = os.getenv("OPENSEARCH_INDEX_PREFIX", "surfsense")

        opensearch = OpenSearchChunkStorage(
            hosts=opensearch_hosts, index_prefix=index_prefix
        )

        async for session in get_async_session():
            # Get search spaces
            result = await session.execute(
                select(Document.search_space_id).distinct()
            )
            search_space_ids = [row[0] for row in result.all()]

            logger.info("\n" + "=" * 80)
            logger.info("VERIFICATION")
            logger.info("=" * 80)

            all_match = True

            for space_id in search_space_ids:
                # Count chunks in PostgreSQL
                pg_count_result = await session.execute(
                    select(func.count(Chunk.id))
                    .join(Document, Chunk.document_id == Document.id)
                    .where(Document.search_space_id == space_id)
                )
                pg_count = pg_count_result.scalar()

                # Count chunks in OpenSearch
                stats = await opensearch.get_index_stats(space_id)
                os_count = stats.get("document_count", 0)

                match = "✓" if pg_count == os_count else "✗"
                logger.info(
                    f"{match} Search Space {space_id}: PostgreSQL={pg_count}, OpenSearch={os_count}"
                )

                if pg_count != os_count:
                    all_match = False

            if all_match:
                logger.info("\n✓ Verification passed! All counts match.")
            else:
                logger.warning(
                    "\n⚠ Verification failed! Some counts don't match. "
                    "Check logs above."
                )

            return all_match

    except Exception as e:
        logger.error(f"Verification failed: {e}", exc_info=True)
        return False


async def main():
    """Main migration workflow."""
    logger.info("=" * 80)
    logger.info("PostgreSQL → OpenSearch Migration")
    logger.info("=" * 80)

    # Run migration
    success = await migrate_chunks()

    if not success:
        logger.error("Migration failed. Exiting.")
        sys.exit(1)

    # Verify migration
    logger.info("\nRunning verification...")
    verified = await verify_migration()

    if verified:
        logger.info("\n✓ Migration and verification successful!")
        sys.exit(0)
    else:
        logger.warning("\n⚠ Migration completed but verification failed.")
        sys.exit(1)


if __name__ == "__main__":
    # Ensure we're in the right directory for imports
    if os.path.exists("/app"):
        sys.path.insert(0, "/app")  # Docker container path
    
    asyncio.run(main())
