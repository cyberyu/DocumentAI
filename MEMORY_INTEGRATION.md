# Agent Long-term Memory Integration Guide

## Overview

This guide shows how to add **long-term memory** to SurfSense DeepAgents using OpenSearch. Agents can now:

✅ **Remember conversations** across sessions  
✅ **Learn user preferences** (response style, document format)  
✅ **Store facts** discovered during research  
✅ **Track entities** (people, companies, locations) across documents

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     SurfSense DeepAgent                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Query: "What did we discuss about Microsoft revenue?" │   │
│  └───────────────────┬──────────────────────────────────┘   │
│                      │                                       │
│                      ▼                                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            Memory-Enhanced Agent                      │   │
│  │  1. Search episodic memory (past conversations)      │   │
│  │  2. Search semantic memory (learned facts)           │   │
│  │  3. Get user preferences (response style)            │   │
│  │  4. Assemble context for LLM                         │   │
│  └───────────────────┬──────────────────────────────────┘   │
│                      │                                       │
└──────────────────────┼───────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   OpenSearch Memory Store                    │
│  ┌────────────────┐  ┌────────────────┐  ┌───────────────┐ │
│  │  Episodic      │  │  Semantic      │  │  Procedural   │ │
│  │  (Convos)      │  │  (Facts)       │  │  (Prefs)      │ │
│  │                │  │                │  │               │ │
│  │ Vector + Text  │  │ Vector + Text  │  │  Key-Value    │ │
│  └────────────────┘  └────────────────┘  └───────────────┘ │
│  ┌────────────────┐                                         │
│  │  Entity        │  Per-user indices (data isolation)      │
│  │  (People/Orgs) │  Automatic expiration (TTL)            │
│  └────────────────┘  Hybrid semantic + keyword search      │
└─────────────────────────────────────────────────────────────┘
```

---

## Memory Types

### 1. Episodic Memory (Conversation History)

Stores **conversation turns** with full context:

```python
from adapter_memory import EpisodicMemory, MemoryImportance

# After each conversation turn
memory = EpisodicMemory(
    user_id="user_123",
    conversation_id="conv_456",
    turn_index=3,
    user_message="What was Microsoft's revenue last quarter?",
    agent_response="Microsoft reported Q1 FY26 revenue of $65.6B...",
    documents_used=["msft_10q.pdf"],
    tools_used=["document_search", "calculator"],
    importance=MemoryImportance.MEDIUM,
    tags=["finance", "microsoft", "q1_2026"]
)

memory_adapter.store_memory(memory)
```

**Use cases:**
- "What did we discuss last week?"
- "Continue our previous conversation about X"
- Follow-up questions without repeating context

---

### 2. Semantic Memory (Facts & Knowledge)

Stores **learned facts** from documents or user corrections:

```python
from adapter_memory import SemanticMemory, MemoryImportance

# When agent learns a fact
fact_memory = SemanticMemory(
    user_id="user_123",
    fact="Microsoft's Q1 FY26 revenue was $65.6B, up 16% YoY",
    content="In Q1 FY26, Microsoft reported revenue of $65.6 billion, representing 16% year-over-year growth driven by Azure and cloud services.",
    source="MSFT_FY26Q1_10Q.pdf",
    confidence=0.95,
    verified=True,
    importance=MemoryImportance.HIGH,
    tags=["microsoft", "revenue", "q1_2026"],
    entities=["Microsoft", "Azure"]
)

memory_adapter.store_memory(fact_memory)
```

**Use cases:**
- "What did you learn about Microsoft from the 10-Q?"
- Cross-document fact retrieval
- Fact verification and correction

---

### 3. Procedural Memory (User Preferences)

Stores **user preferences** and workflow patterns:

```python
from adapter_memory import ProceduralMemory, MemoryImportance

# User prefers concise responses
pref_memory = ProceduralMemory(
    user_id="user_123",
    preference_key="response_style",
    preference_value="concise",
    content="User prefers brief, bullet-point answers for financial data",
    context="When answering financial queries",
    importance=MemoryImportance.CRITICAL,  # Never expires
    tags=["preference", "style"]
)

memory_adapter.store_memory(pref_memory)

# User's preferred document format
format_pref = ProceduralMemory(
    user_id="user_123",
    preference_key="document_format",
    preference_value="markdown_tables",
    content="User wants financial data in Markdown tables, not paragraphs",
    importance=MemoryImportance.CRITICAL
)

memory_adapter.store_memory(format_pref)
```

**Use cases:**
- Personalized response formatting
- Remembering user's domain (finance, legal, healthcare)
- Workflow preferences (always show sources, skip explanations)

---

### 4. Entity Memory (People, Organizations, Locations)

Tracks **entities** across documents and conversations:

```python
from adapter_memory import EntityMemory, MemoryImportance

# Track Microsoft entity
entity_memory = EntityMemory(
    user_id="user_123",
    entity_name="Microsoft",
    entity_type="organization",
    content="Microsoft Corporation: Tech company, NYSE: MSFT, CEO: Satya Nadella",
    aliases=["MSFT", "Microsoft Corporation", "MS"],
    attributes={
        "industry": "Technology",
        "stock_ticker": "MSFT",
        "ceo": "Satya Nadella",
        "founded": "1975"
    },
    mention_count=42,
    importance=MemoryImportance.HIGH,
    tags=["company", "technology"]
)

memory_adapter.store_memory(entity_memory)
```

**Use cases:**
- "Tell me more about Microsoft" (without re-searching)
- Entity disambiguation (IBM vs IBM Research)
- Cross-document entity tracking

---

## Integration with SurfSense DeepAgents

### Step 1: Initialize Memory Adapter

```python
# In SurfSense backend initialization (e.g., app/services/agent_service.py)

from adapter_memory import OpenSearchMemoryAdapter
from adapter_examples import OpenSearchAdapter, FastEmbedAdapter

# Initialize adapters
embedding_adapter = FastEmbedAdapter({
    "model_name": "BAAI/bge-small-en-v1.5"
})

storage_adapter = OpenSearchAdapter({
    "opensearch_hosts": ["http://opensearch:9200"],
    "index_name": "documents"
})

# Initialize memory adapter
memory_adapter = OpenSearchMemoryAdapter(
    storage=storage_adapter,
    embedding=embedding_adapter,
    config={
        "opensearch_hosts": ["http://opensearch:9200"],
        "index_prefix": "agent_memory"
    }
)
```

### Step 2: Store Memories During Conversation

```python
# In your agent conversation handler

async def handle_user_query(
    user_id: str,
    conversation_id: str,
    user_message: str,
    turn_index: int
) -> str:
    # 1. Retrieve relevant memories
    memory_results = memory_adapter.search_memories(
        query=user_message,
        user_id=user_id,
        memory_types=[MemoryType.EPISODIC, MemoryType.SEMANTIC],
        top_k=5,
        time_window=timedelta(days=30)  # Last 30 days
    )
    
    # 2. Get user preferences
    preferences = memory_adapter.get_user_preferences(user_id)
    response_style = preferences.get("response_style", "detailed")
    
    # 3. Format memories as context
    from adapter_memory import format_memories_for_agent
    memory_context = format_memories_for_agent(memory_results, max_tokens=1500)
    
    # 4. Build enhanced prompt
    enhanced_prompt = f"""You are a helpful assistant with long-term memory.

User's Preferences:
- Response style: {response_style}

Relevant Past Context:
{memory_context}

Current Query:
{user_message}

Respond naturally, referencing past context when relevant."""
    
    # 5. Get response from LLM (existing SurfSense logic)
    agent_response = await your_agent_generate_response(enhanced_prompt)
    
    # 6. Store this conversation turn
    episodic_memory = EpisodicMemory(
        user_id=user_id,
        conversation_id=conversation_id,
        turn_index=turn_index,
        user_message=user_message,
        agent_response=agent_response,
        importance=MemoryImportance.MEDIUM,
        tags=extract_tags(user_message)  # Your tag extraction logic
    )
    memory_adapter.store_memory(episodic_memory)
    
    # 7. Extract and store facts (optional)
    facts = extract_facts_from_response(agent_response)
    for fact in facts:
        semantic_memory = SemanticMemory(
            user_id=user_id,
            fact=fact["text"],
            content=fact["text"],
            source="agent_conversation",
            confidence=fact["confidence"],
            importance=MemoryImportance.MEDIUM,
            tags=fact["tags"]
        )
        memory_adapter.store_memory(semantic_memory)
    
    return agent_response
```

### Step 3: Handle User Preferences

```python
# When user sets a preference
async def set_user_preference(user_id: str, key: str, value: Any):
    pref_memory = ProceduralMemory(
        user_id=user_id,
        preference_key=key,
        preference_value=value,
        content=f"User prefers {key}: {value}",
        importance=MemoryImportance.CRITICAL  # Never expires
    )
    memory_adapter.store_memory(pref_memory)

# Examples of preference setting
await set_user_preference("user_123", "response_style", "concise")
await set_user_preference("user_123", "document_format", "markdown")
await set_user_preference("user_123", "domain", "finance")
```

### Step 4: Background Cleanup

```python
# In Celery beat scheduler (periodic task)

from celery import shared_task

@shared_task
def cleanup_expired_memories():
    """Remove expired memories daily"""
    from adapter_memory import OpenSearchMemoryAdapter
    
    # Initialize adapter
    memory_adapter = get_memory_adapter()
    
    # Cleanup
    deleted_count = memory_adapter.cleanup_expired_memories()
    
    logger.info(f"Cleaned up {deleted_count} expired memories")
    return deleted_count

# Schedule in celerybeat-schedule.py
CELERY_BEAT_SCHEDULE = {
    'cleanup-expired-memories': {
        'task': 'app.tasks.cleanup_expired_memories',
        'schedule': crontab(hour=2, minute=0),  # 2 AM daily
    },
}
```

---

## Docker Configuration

Update `docker-compose-adaptable-rag.yml` to mount memory adapter:

```yaml
services:
  backend:
    volumes:
      # Existing mounts
      - ./adapter_base_classes.py:/app/app/adapters/adapter_base_classes.py:ro
      - ./adapter_dataflow_models.py:/app/app/adapters/adapter_dataflow_models.py:ro
      - ./adapter_examples.py:/app/app/adapters/adapter_examples.py:ro
      # New: Memory adapter
      - ./adapter_memory.py:/app/app/adapters/adapter_memory.py:ro
  
  celery_worker:
    volumes:
      # Same as backend
      - ./adapter_memory.py:/app/app/adapters/adapter_memory.py:ro
  
  opensearch:
    environment:
      # Increase heap for memory storage
      - "OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g"
```

---

## Memory Search Strategies

### 1. Hybrid Search (Semantic + Keyword)

```python
# Best for general queries
results = memory_adapter.search_memories(
    query="Microsoft revenue growth",
    user_id="user_123",
    top_k=10
)
```

### 2. Recency-Biased Search

```python
# Only last 7 days
results = memory_adapter.search_memories(
    query="our discussion about AI",
    user_id="user_123",
    time_window=timedelta(days=7),
    top_k=5
)
```

### 3. Importance-Filtered Search

```python
from adapter_memory import MemoryImportance

# Only critical/high importance
results = memory_adapter.search_memories(
    query="user preferences",
    user_id="user_123",
    min_importance=MemoryImportance.HIGH,
    top_k=10
)
```

### 4. Type-Specific Search

```python
from adapter_memory import MemoryType

# Only facts (semantic memory)
facts = memory_adapter.search_memories(
    query="Microsoft financial data",
    user_id="user_123",
    memory_types=[MemoryType.SEMANTIC],
    top_k=10
)

# Only past conversations
conversations = memory_adapter.search_memories(
    query="what we discussed",
    user_id="user_123",
    memory_types=[MemoryType.EPISODIC],
    top_k=5
)
```

---

## Memory Retention Policies

Automatic expiration based on importance:

| Importance | Retention | Use Cases |
|-----------|-----------|-----------|
| **CRITICAL** | Never expires | User preferences, account settings |
| **HIGH** | 30 days | Important facts, key conversations |
| **MEDIUM** | 7 days | Regular conversations, routine facts |
| **LOW** | 1 day | Temporary context, system messages |

Override expiration:

```python
memory = SemanticMemory(
    user_id="user_123",
    fact="Important regulatory change",
    importance=MemoryImportance.HIGH,
    expires_at=None  # Never expires (override policy)
)
```

---

## Performance Optimization

### 1. Per-User Indices

Each user gets separate indices for **data isolation** and **fast search**:

```
agent_memory_episodic_user_123
agent_memory_semantic_user_123
agent_memory_procedural_user_123
agent_memory_entity_user_123
```

### 2. Lazy Index Creation

Indices created only when first memory is stored (no empty indices).

### 3. Batch Storage

Store multiple memories efficiently:

```python
memories = [memory1, memory2, memory3]
for memory in memories:
    memory_adapter.store_memory(memory)  # Could be batched in future
```

### 4. Access Count Tracking

Frequently accessed memories get **boosted scoring** (implicit importance).

---

## Example Use Cases

### Use Case 1: Follow-up Questions

**Without Memory:**
```
User: "What was Microsoft's revenue last quarter?"
Agent: "$65.6B"

User: "And the quarter before?"
Agent: "I don't have context about previous quarters mentioned."
```

**With Memory:**
```
User: "What was Microsoft's revenue last quarter?"
Agent: "$65.6B in Q1 FY26"

User: "And the quarter before?"
Agent: "Looking at our previous discussion, you asked about Q1 FY26 ($65.6B). 
       Q4 FY25 was $62.0B."
```

### Use Case 2: Learning User Preferences

**First Conversation:**
```
User: "Give me Microsoft's financials"
Agent: [Long detailed response]
User: "Too verbose. Just bullet points please."
Agent: "Got it! I'll use bullet points for financial data."
[Stores: preference_key="response_style", value="bullet_points", context="financial_data"]
```

**Later Conversation:**
```
User: "Show me Apple's financials"
Agent: [Retrieves preference: response_style=bullet_points]
       • Q1 Revenue: $97.3B
       • Net Income: $24.2B
       • EPS: $1.53
```

### Use Case 3: Cross-Document Entity Tracking

```python
# User uploads multiple documents about Microsoft
# Agent extracts entity info across all docs

entity = memory_adapter.get_entity_info("user_123", "Microsoft")

# Returns consolidated info:
# - Mentioned in: 10-Q (Q1), 10-K (annual), news article
# - Key facts: Revenue $65.6B, CEO Satya Nadella, Azure growth 31%
# - Related entities: Azure, Office 365, GitHub
```

---

## Monitoring & Debugging

### Check Memory Usage

```python
# Get all memories for a user
from adapter_memory import MemoryType

for memory_type in MemoryType:
    index_name = f"agent_memory_{memory_type.value}_user_123"
    count = opensearch_client.count(index=index_name)
    print(f"{memory_type.value}: {count['count']} memories")
```

### View Recent Conversations

```python
# Get last 10 conversation turns
recent = memory_adapter.get_recent_conversation(
    user_id="user_123",
    conversation_id="conv_456",
    limit=10
)

for turn in recent:
    print(f"Turn {turn.turn_index}:")
    print(f"  User: {turn.user_message}")
    print(f"  Agent: {turn.agent_response}")
```

### Search Logs

```python
# All logs stored in OpenSearch with:
# - memory_id
# - timestamp
# - user_id
# - memory_type
# - access_count

# High-value memories (frequently accessed)
high_value = memory_adapter.search_memories(
    query="",  # Empty query = all memories
    user_id="user_123",
    top_k=20
)

for result in high_value:
    if result.memory.access_count > 10:
        print(f"High-value memory: {result.memory.content[:50]}...")
        print(f"  Accessed {result.memory.access_count} times")
```

---

## Migration Path

### Phase 1: Basic Memory (Current)
- ✅ Store conversation history
- ✅ Basic preference storage
- ✅ Semantic search

### Phase 2: Advanced Memory (Future)
- Automatic fact extraction from responses
- Memory consolidation (merge similar memories)
- Cross-user knowledge sharing (optional, with privacy controls)
- Memory importance learning (ML-based)

### Phase 3: Distributed Memory (Scale)
- Multi-node OpenSearch cluster
- Memory replication across regions
- Federated search across users (enterprise)

---

## Security & Privacy

### Data Isolation

Each user has **separate indices** - no cross-user data leakage:

```python
# User 123 cannot access User 456's memories
memory_adapter.search_memories(
    query="anything",
    user_id="user_456"  # Required - enforces isolation
)
```

### Encryption

```yaml
# In docker-compose-adaptable-rag.yml
services:
  opensearch:
    environment:
      - plugins.security.ssl.http.enabled=true
      - OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g
    volumes:
      - ./opensearch-certs:/usr/share/opensearch/config/certificates:ro
```

### GDPR Compliance

```python
# Delete all user memories (right to be forgotten)
def delete_user_memories(user_id: str):
    for memory_type in MemoryType:
        index_name = f"agent_memory_{memory_type.value}_{user_id}"
        opensearch_client.indices.delete(index=index_name, ignore=[404])
```

---

## Next Steps

1. **Mount memory adapter** in docker-compose ✅ (see Docker Configuration above)
2. **Initialize in SurfSense backend** (add to app initialization)
3. **Integrate with DeepAgents** (modify conversation handler)
4. **Test with sample conversations** (verify memory storage/retrieval)
5. **Monitor memory growth** (set up cleanup task)
6. **Add user preference UI** (let users control their preferences)

---

**Ready to deploy!** Memory adapter works with your existing OpenSearch instance - no additional infrastructure needed.
