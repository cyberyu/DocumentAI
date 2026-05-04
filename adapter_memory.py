"""
Memory Adapter - Long-term Memory for Agents using OpenSearch

Stores and retrieves agent memory in OpenSearch:
1. Episodic Memory: Conversation history with semantic search
2. Semantic Memory: Facts, concepts, learned information
3. Procedural Memory: User preferences, workflow patterns
4. Entity Memory: People, places, things mentioned across conversations

Design:
- Uses separate OpenSearch indices for each memory type
- Vector embeddings for semantic retrieval
- Metadata filtering (user_id, session_id, timestamp)
- TTL support for memory decay
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import uuid

from adapter_dataflow_models import Query
from adapter_base_classes import EmbeddingAdapter, StorageAdapter


# ============================================================================
# MEMORY DATA MODELS
# ============================================================================

class MemoryType(str, Enum):
    """Types of agent memory"""
    EPISODIC = "episodic"        # Conversation history
    SEMANTIC = "semantic"         # Facts, concepts
    PROCEDURAL = "procedural"     # Preferences, workflows
    ENTITY = "entity"             # People, places, things


class MemoryImportance(str, Enum):
    """Memory importance for retention"""
    CRITICAL = "critical"         # Never forget (user preferences)
    HIGH = "high"                 # Important facts (30 day retention)
    MEDIUM = "medium"             # Useful context (7 day retention)
    LOW = "low"                   # Temporary (1 day retention)


@dataclass
class Memory:
    """Base memory unit"""
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    memory_type: MemoryType = MemoryType.EPISODIC
    
    # Content
    content: str = ""             # Main memory text
    embedding: List[float] = field(default_factory=list)  # Vector for semantic search
    
    # Context
    user_id: str = ""
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    
    # Metadata
    importance: MemoryImportance = MemoryImportance.MEDIUM
    tags: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)  # Extracted entities
    
    # Temporal
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    access_count: int = 0
    
    # Relations
    related_memory_ids: List[str] = field(default_factory=list)
    source_document_id: Optional[str] = None
    
    # Custom metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EpisodicMemory(Memory):
    """Conversation turn memory"""
    memory_type: MemoryType = field(default=MemoryType.EPISODIC, init=False)
    
    # Conversation details
    user_message: str = ""
    agent_response: str = ""
    turn_index: int = 0
    
    # Context at time of conversation
    documents_used: List[str] = field(default_factory=list)
    tools_used: List[str] = field(default_factory=list)
    reasoning_steps: List[str] = field(default_factory=list)


@dataclass
class SemanticMemory(Memory):
    """Fact/concept memory"""
    memory_type: MemoryType = field(default=MemoryType.SEMANTIC, init=False)
    
    # Fact details
    fact: str = ""                # The core fact
    confidence: float = 1.0       # Confidence in this fact
    source: str = ""              # Where this came from
    verified: bool = False        # Has been verified


@dataclass
class ProceduralMemory(Memory):
    """Preference/workflow memory"""
    memory_type: MemoryType = field(default=MemoryType.PROCEDURAL, init=False)
    
    # Preference details
    preference_key: str = ""      # e.g., "response_style", "document_format"
    preference_value: Any = None
    context: str = ""             # When this preference applies


@dataclass
class EntityMemory(Memory):
    """Entity (person, place, thing) memory"""
    memory_type: MemoryType = field(default=MemoryType.ENTITY, init=False)
    
    # Entity details
    entity_name: str = ""
    entity_type: str = ""         # "person", "organization", "location", etc.
    aliases: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    first_mentioned_at: Optional[datetime] = None
    mention_count: int = 0


@dataclass
class MemorySearchResult:
    """Result from memory search"""
    memory: Memory
    score: float                  # Relevance score
    recency_score: float          # How recent
    importance_score: float       # Importance weight
    combined_score: float         # Final score


# ============================================================================
# MEMORY ADAPTER BASE CLASS
# ============================================================================

class MemoryAdapter(ABC):
    """
    Base class for agent memory storage and retrieval.
    
    Supports multiple memory types with semantic + temporal search.
    """
    
    def __init__(
        self,
        storage: StorageAdapter,
        embedding: EmbeddingAdapter,
        config: Dict[str, Any]
    ):
        self.storage = storage
        self.embedding = embedding
        self.config = config
        
        # Memory retention policies (days)
        self.retention_policies = {
            MemoryImportance.CRITICAL: None,  # Never expire
            MemoryImportance.HIGH: 30,
            MemoryImportance.MEDIUM: 7,
            MemoryImportance.LOW: 1,
        }
    
    @abstractmethod
    def store_memory(self, memory: Memory) -> str:
        """
        Store a memory.
        
        Args:
            memory: Memory object to store
            
        Returns:
            memory_id: ID of stored memory
        """
        pass
    
    @abstractmethod
    def search_memories(
        self,
        query: str,
        user_id: str,
        memory_types: Optional[List[MemoryType]] = None,
        top_k: int = 10,
        time_window: Optional[timedelta] = None,
        min_importance: Optional[MemoryImportance] = None
    ) -> List[MemorySearchResult]:
        """
        Search memories semantically.
        
        Args:
            query: Search query
            user_id: User ID to filter by
            memory_types: Types of memory to search
            top_k: Number of results
            time_window: Only return memories within this time window
            min_importance: Minimum importance level
            
        Returns:
            List of MemorySearchResult objects
        """
        pass
    
    @abstractmethod
    def get_recent_conversation(
        self,
        user_id: str,
        conversation_id: str,
        limit: int = 10
    ) -> List[EpisodicMemory]:
        """Get recent conversation history"""
        pass
    
    @abstractmethod
    def get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """Get all user preferences"""
        pass
    
    @abstractmethod
    def get_entity_info(self, user_id: str, entity_name: str) -> Optional[EntityMemory]:
        """Get information about a specific entity"""
        pass
    
    @abstractmethod
    def cleanup_expired_memories(self) -> int:
        """Remove expired memories, return count"""
        pass
    
    def _compute_combined_score(
        self,
        semantic_score: float,
        memory: Memory,
        current_time: datetime
    ) -> float:
        """
        Compute combined score from semantic relevance, recency, and importance.
        
        Score = semantic_score * recency_weight * importance_weight
        """
        # Recency weight (decay over time)
        age_hours = (current_time - memory.last_accessed_at).total_seconds() / 3600
        recency_weight = 1.0 / (1.0 + age_hours / 24)  # Decay over days
        
        # Importance weight
        importance_weights = {
            MemoryImportance.CRITICAL: 2.0,
            MemoryImportance.HIGH: 1.5,
            MemoryImportance.MEDIUM: 1.0,
            MemoryImportance.LOW: 0.5,
        }
        importance_weight = importance_weights[memory.importance]
        
        # Access frequency boost (popular memories)
        access_boost = min(1.0 + (memory.access_count * 0.1), 2.0)
        
        combined = semantic_score * recency_weight * importance_weight * access_boost
        return combined


# ============================================================================
# OPENSEARCH MEMORY ADAPTER
# ============================================================================

class OpenSearchMemoryAdapter(MemoryAdapter):
    """
    Memory storage using OpenSearch.
    
    Uses separate indices for each memory type:
    - agent_memory_episodic_{user_id}
    - agent_memory_semantic_{user_id}
    - agent_memory_procedural_{user_id}
    - agent_memory_entity_{user_id}
    """
    
    def __init__(
        self,
        storage: StorageAdapter,
        embedding: EmbeddingAdapter,
        config: Dict[str, Any]
    ):
        super().__init__(storage, embedding, config)
        
        # Import OpenSearch client
        from opensearchpy import OpenSearch
        self.client = OpenSearch(
            hosts=config.get("opensearch_hosts", ["http://localhost:9200"]),
            timeout=30,
        )
        
        self.index_prefix = config.get("index_prefix", "agent_memory")
    
    def _get_index_name(self, user_id: str, memory_type: MemoryType) -> str:
        """Get index name for user and memory type"""
        # Per-user indices for data isolation
        return f"{self.index_prefix}_{memory_type.value}_{user_id}"
    
    def _ensure_index(self, user_id: str, memory_type: MemoryType):
        """Create memory index if doesn't exist"""
        index_name = self._get_index_name(user_id, memory_type)
        
        if self.client.indices.exists(index=index_name):
            return
        
        # Get embedding dimensions
        embedding_dims = self.embedding.get_dimensions()
        
        index_body = {
            "settings": {
                "index": {
                    "knn": True,
                    "number_of_shards": 1,
                }
            },
            "mappings": {
                "properties": {
                    "memory_id": {"type": "keyword"},
                    "memory_type": {"type": "keyword"},
                    "content": {"type": "text"},  # Full-text search
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": embedding_dims,
                        "method": {
                            "name": "hnsw",
                            "engine": "faiss",
                        }
                    },
                    "user_id": {"type": "keyword"},
                    "session_id": {"type": "keyword"},
                    "conversation_id": {"type": "keyword"},
                    "importance": {"type": "keyword"},
                    "tags": {"type": "keyword"},
                    "entities": {"type": "keyword"},
                    "created_at": {"type": "date"},
                    "last_accessed_at": {"type": "date"},
                    "expires_at": {"type": "date"},
                    "access_count": {"type": "integer"},
                    
                    # Type-specific fields
                    "user_message": {"type": "text"},
                    "agent_response": {"type": "text"},
                    "turn_index": {"type": "integer"},
                    "fact": {"type": "text"},
                    "confidence": {"type": "float"},
                    "preference_key": {"type": "keyword"},
                    "preference_value": {"type": "text"},
                    "entity_name": {"type": "keyword"},
                    "entity_type": {"type": "keyword"},
                    "mention_count": {"type": "integer"},
                    
                    "metadata": {"type": "object"},
                }
            }
        }
        
        self.client.indices.create(index=index_name, body=index_body)
    
    def store_memory(self, memory: Memory) -> str:
        """Store memory in OpenSearch"""
        # Generate embedding if not present
        if not memory.embedding:
            memory.embedding = self.embedding.embed_query(memory.content)
        
        # Set expiration based on importance
        if memory.expires_at is None and memory.importance != MemoryImportance.CRITICAL:
            retention_days = self.retention_policies[memory.importance]
            memory.expires_at = memory.created_at + timedelta(days=retention_days)
        
        # Ensure index exists
        self._ensure_index(memory.user_id, memory.memory_type)
        index_name = self._get_index_name(memory.user_id, memory.memory_type)
        
        # Convert to dict for indexing
        doc = {
            "memory_id": memory.memory_id,
            "memory_type": memory.memory_type.value,
            "content": memory.content,
            "embedding": memory.embedding,
            "user_id": memory.user_id,
            "session_id": memory.session_id,
            "conversation_id": memory.conversation_id,
            "importance": memory.importance.value,
            "tags": memory.tags,
            "entities": memory.entities,
            "created_at": memory.created_at.isoformat(),
            "last_accessed_at": memory.last_accessed_at.isoformat(),
            "expires_at": memory.expires_at.isoformat() if memory.expires_at else None,
            "access_count": memory.access_count,
            "related_memory_ids": memory.related_memory_ids,
            "source_document_id": memory.source_document_id,
            "metadata": memory.metadata,
        }
        
        # Add type-specific fields
        if isinstance(memory, EpisodicMemory):
            doc.update({
                "user_message": memory.user_message,
                "agent_response": memory.agent_response,
                "turn_index": memory.turn_index,
                "documents_used": memory.documents_used,
                "tools_used": memory.tools_used,
            })
        elif isinstance(memory, SemanticMemory):
            doc.update({
                "fact": memory.fact,
                "confidence": memory.confidence,
                "source": memory.source,
                "verified": memory.verified,
            })
        elif isinstance(memory, ProceduralMemory):
            doc.update({
                "preference_key": memory.preference_key,
                "preference_value": str(memory.preference_value),
                "context": memory.context,
            })
        elif isinstance(memory, EntityMemory):
            doc.update({
                "entity_name": memory.entity_name,
                "entity_type": memory.entity_type,
                "aliases": memory.aliases,
                "attributes": memory.attributes,
                "mention_count": memory.mention_count,
            })
        
        # Index
        self.client.index(
            index=index_name,
            id=memory.memory_id,
            body=doc,
            refresh=True  # Make immediately searchable
        )
        
        return memory.memory_id
    
    def search_memories(
        self,
        query: str,
        user_id: str,
        memory_types: Optional[List[MemoryType]] = None,
        top_k: int = 10,
        time_window: Optional[timedelta] = None,
        min_importance: Optional[MemoryImportance] = None
    ) -> List[MemorySearchResult]:
        """Search memories with hybrid semantic + keyword search"""
        
        if memory_types is None:
            memory_types = list(MemoryType)
        
        # Generate query embedding
        query_embedding = self.embedding.embed_query(query)
        
        results = []
        current_time = datetime.utcnow()
        
        for memory_type in memory_types:
            index_name = self._get_index_name(user_id, memory_type)
            
            if not self.client.indices.exists(index=index_name):
                continue
            
            # Build query
            must_clauses = [
                {"term": {"user_id": user_id}}
            ]
            
            # Time window filter
            if time_window:
                cutoff_time = current_time - time_window
                must_clauses.append({
                    "range": {
                        "created_at": {"gte": cutoff_time.isoformat()}
                    }
                })
            
            # Importance filter
            if min_importance:
                importance_order = [
                    MemoryImportance.LOW,
                    MemoryImportance.MEDIUM,
                    MemoryImportance.HIGH,
                    MemoryImportance.CRITICAL
                ]
                min_idx = importance_order.index(min_importance)
                allowed_importances = [imp.value for imp in importance_order[min_idx:]]
                must_clauses.append({
                    "terms": {"importance": allowed_importances}
                })
            
            # Exclude expired memories
            must_clauses.append({
                "bool": {
                    "should": [
                        {"bool": {"must_not": {"exists": {"field": "expires_at"}}}},
                        {"range": {"expires_at": {"gt": current_time.isoformat()}}}
                    ]
                }
            })
            
            # Hybrid search: k-NN + keyword
            search_body = {
                "size": top_k,
                "query": {
                    "bool": {
                        "must": must_clauses,
                        "should": [
                            # Semantic search (k-NN)
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": query_embedding,
                                        "k": top_k
                                    }
                                }
                            },
                            # Keyword search
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": ["content^2", "user_message", "agent_response", "fact"],
                                    "boost": 0.5
                                }
                            }
                        ]
                    }
                }
            }
            
            response = self.client.search(index=index_name, body=search_body)
            
            # Process results
            for hit in response["hits"]["hits"]:
                source = hit["_source"]
                semantic_score = hit["_score"]
                
                # Reconstruct memory object
                memory = self._dict_to_memory(source)
                
                # Compute combined score
                recency_score = 1.0 / (1.0 + (current_time - memory.last_accessed_at).days)
                importance_weights = {
                    MemoryImportance.CRITICAL: 2.0,
                    MemoryImportance.HIGH: 1.5,
                    MemoryImportance.MEDIUM: 1.0,
                    MemoryImportance.LOW: 0.5,
                }
                importance_score = importance_weights[memory.importance]
                
                combined_score = self._compute_combined_score(
                    semantic_score, memory, current_time
                )
                
                results.append(MemorySearchResult(
                    memory=memory,
                    score=semantic_score,
                    recency_score=recency_score,
                    importance_score=importance_score,
                    combined_score=combined_score
                ))
                
                # Update access count
                self.client.update(
                    index=index_name,
                    id=memory.memory_id,
                    body={
                        "doc": {
                            "access_count": memory.access_count + 1,
                            "last_accessed_at": current_time.isoformat()
                        }
                    }
                )
        
        # Sort by combined score
        results.sort(key=lambda x: x.combined_score, reverse=True)
        return results[:top_k]
    
    def get_recent_conversation(
        self,
        user_id: str,
        conversation_id: str,
        limit: int = 10
    ) -> List[EpisodicMemory]:
        """Get recent conversation turns"""
        index_name = self._get_index_name(user_id, MemoryType.EPISODIC)
        
        if not self.client.indices.exists(index=index_name):
            return []
        
        search_body = {
            "size": limit,
            "query": {
                "bool": {
                    "must": [
                        {"term": {"user_id": user_id}},
                        {"term": {"conversation_id": conversation_id}}
                    ]
                }
            },
            "sort": [{"turn_index": {"order": "desc"}}]
        }
        
        response = self.client.search(index=index_name, body=search_body)
        
        memories = []
        for hit in response["hits"]["hits"]:
            memory = self._dict_to_memory(hit["_source"])
            if isinstance(memory, EpisodicMemory):
                memories.append(memory)
        
        return memories[::-1]  # Return in chronological order
    
    def get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """Get all user preferences"""
        index_name = self._get_index_name(user_id, MemoryType.PROCEDURAL)
        
        if not self.client.indices.exists(index=index_name):
            return {}
        
        search_body = {
            "size": 100,
            "query": {"term": {"user_id": user_id}}
        }
        
        response = self.client.search(index=index_name, body=search_body)
        
        preferences = {}
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            key = source.get("preference_key")
            value = source.get("preference_value")
            if key:
                preferences[key] = value
        
        return preferences
    
    def get_entity_info(self, user_id: str, entity_name: str) -> Optional[EntityMemory]:
        """Get entity information"""
        index_name = self._get_index_name(user_id, MemoryType.ENTITY)
        
        if not self.client.indices.exists(index=index_name):
            return None
        
        search_body = {
            "size": 1,
            "query": {
                "bool": {
                    "must": [
                        {"term": {"user_id": user_id}},
                        {"term": {"entity_name": entity_name.lower()}}
                    ]
                }
            }
        }
        
        response = self.client.search(index=index_name, body=search_body)
        
        if response["hits"]["total"]["value"] > 0:
            source = response["hits"]["hits"][0]["_source"]
            memory = self._dict_to_memory(source)
            if isinstance(memory, EntityMemory):
                return memory
        
        return None
    
    def cleanup_expired_memories(self) -> int:
        """Remove expired memories"""
        deleted_count = 0
        current_time = datetime.utcnow()
        
        # Search all indices
        for memory_type in MemoryType:
            # Get all user indices for this type
            indices = self.client.cat.indices(
                index=f"{self.index_prefix}_{memory_type.value}_*",
                format="json"
            )
            
            for index_info in indices:
                index_name = index_info["index"]
                
                # Delete expired memories
                result = self.client.delete_by_query(
                    index=index_name,
                    body={
                        "query": {
                            "range": {
                                "expires_at": {"lt": current_time.isoformat()}
                            }
                        }
                    }
                )
                
                deleted_count += result["deleted"]
        
        return deleted_count
    
    def _dict_to_memory(self, doc: Dict[str, Any]) -> Memory:
        """Convert OpenSearch document to Memory object"""
        memory_type = MemoryType(doc["memory_type"])
        
        # Common fields
        common_fields = {
            "memory_id": doc["memory_id"],
            "content": doc["content"],
            "embedding": doc.get("embedding", []),
            "user_id": doc["user_id"],
            "session_id": doc.get("session_id"),
            "conversation_id": doc.get("conversation_id"),
            "importance": MemoryImportance(doc["importance"]),
            "tags": doc.get("tags", []),
            "entities": doc.get("entities", []),
            "created_at": datetime.fromisoformat(doc["created_at"]),
            "last_accessed_at": datetime.fromisoformat(doc["last_accessed_at"]),
            "expires_at": datetime.fromisoformat(doc["expires_at"]) if doc.get("expires_at") else None,
            "access_count": doc.get("access_count", 0),
            "related_memory_ids": doc.get("related_memory_ids", []),
            "metadata": doc.get("metadata", {}),
        }
        
        if memory_type == MemoryType.EPISODIC:
            return EpisodicMemory(
                **common_fields,
                user_message=doc.get("user_message", ""),
                agent_response=doc.get("agent_response", ""),
                turn_index=doc.get("turn_index", 0),
                documents_used=doc.get("documents_used", []),
                tools_used=doc.get("tools_used", []),
            )
        elif memory_type == MemoryType.SEMANTIC:
            return SemanticMemory(
                **common_fields,
                fact=doc.get("fact", ""),
                confidence=doc.get("confidence", 1.0),
                source=doc.get("source", ""),
                verified=doc.get("verified", False),
            )
        elif memory_type == MemoryType.PROCEDURAL:
            return ProceduralMemory(
                **common_fields,
                preference_key=doc.get("preference_key", ""),
                preference_value=doc.get("preference_value"),
                context=doc.get("context", ""),
            )
        elif memory_type == MemoryType.ENTITY:
            return EntityMemory(
                **common_fields,
                entity_name=doc.get("entity_name", ""),
                entity_type=doc.get("entity_type", ""),
                aliases=doc.get("aliases", []),
                attributes=doc.get("attributes", {}),
                mention_count=doc.get("mention_count", 0),
            )
        else:
            return Memory(**common_fields)


# ============================================================================
# UTILITY: Context Assembly
# ============================================================================

def format_memories_for_agent(
    memories: List[MemorySearchResult],
    max_tokens: int = 2000
) -> str:
    """Format retrieved memories as context for agent"""
    context_parts = []
    total_tokens = 0
    
    for result in memories:
        memory = result.memory
        
        # Format based on memory type
        if isinstance(memory, EpisodicMemory):
            snippet = f"[Past Conversation - {memory.created_at.strftime('%Y-%m-%d')}]\n"
            snippet += f"User: {memory.user_message}\n"
            snippet += f"Assistant: {memory.agent_response}\n"
        
        elif isinstance(memory, SemanticMemory):
            snippet = f"[Fact - Confidence: {memory.confidence:.2f}]\n"
            snippet += f"{memory.fact}\n"
        
        elif isinstance(memory, ProceduralMemory):
            snippet = f"[User Preference: {memory.preference_key}]\n"
            snippet += f"{memory.content}\n"
        
        elif isinstance(memory, EntityMemory):
            snippet = f"[Entity: {memory.entity_name} ({memory.entity_type})]\n"
            snippet += f"{memory.content}\n"
        
        else:
            snippet = f"[Memory]\n{memory.content}\n"
        
        # Rough token count
        tokens = len(snippet.split())
        if total_tokens + tokens > max_tokens:
            break
        
        context_parts.append(snippet)
        total_tokens += tokens
    
    return "\n---\n".join(context_parts)
