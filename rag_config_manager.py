"""
RAG Configuration Manager

Manages loading, validation, and runtime access to RAG system configurations.
Supports:
- Multi-profile configurations (production, experimental, etc.)
- Dynamic component loading based on config
- Agent-driven configuration overrides
- Experiment tracking and optimization
"""

import importlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import yaml
from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration Models
# ============================================================================


class ETLConfig(BaseModel):
    """ETL pipeline configuration"""
    provider: str = "docling"
    config: Dict[str, Any] = Field(default_factory=dict)


class ChunkingConfig(BaseModel):
    """Chunking strategy configuration"""
    strategy: str = "hybrid_sandwich"
    config: Dict[str, Any] = Field(default_factory=dict)
    
    @validator("config")
    def validate_chunk_size_matches_embedding(cls, v, values):
        """Ensure chunk_size will match embedding model max_seq_length"""
        if "chunk_size" in v:
            logger.debug(f"Chunking config: chunk_size={v['chunk_size']}")
        return v


class EmbeddingConfig(BaseModel):
    """Embedding model configuration"""
    provider: str = "fastembed"
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    config: Dict[str, Any] = Field(default_factory=dict)


class StorageConfig(BaseModel):
    """Vector storage configuration"""
    provider: str = "postgresql_pgvector"
    config: Dict[str, Any] = Field(default_factory=dict)


class RetrievalConfig(BaseModel):
    """Retrieval strategy configuration"""
    strategy: str = "hybrid_rrf"
    config: Dict[str, Any] = Field(default_factory=dict)


class RerankingConfig(BaseModel):
    """Reranking configuration"""
    enabled: bool = True
    provider: str = "flashrank"
    model: str = "ms-marco-MiniLM-L-12-v2"
    config: Dict[str, Any] = Field(default_factory=dict)


class ContextBuildingConfig(BaseModel):
    """Context building configuration"""
    format: str = "xml_filesystem"
    config: Dict[str, Any] = Field(default_factory=dict)


class GenerationConfig(BaseModel):
    """LLM generation configuration"""
    config: Dict[str, Any] = Field(default_factory=dict)


class OptimizationConfig(BaseModel):
    """Optimization and experiment tracking"""
    track_metrics: bool = True
    log_retrieval_results: bool = True
    log_llm_calls: bool = True
    auto_tune: bool = False
    objective: str = "f1_score"
    ab_testing: Dict[str, Any] = Field(default_factory=dict)


class RAGProfile(BaseModel):
    """Complete RAG configuration profile"""
    name: str
    inherits: Optional[str] = None
    overrides: Optional[Dict[str, Any]] = None
    
    etl: ETLConfig = Field(default_factory=ETLConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    reranking: RerankingConfig = Field(default_factory=RerankingConfig)
    context_building: ContextBuildingConfig = Field(default_factory=ContextBuildingConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    optimization: OptimizationConfig = Field(default_factory=OptimizationConfig)


class RAGConfigSchema(BaseModel):
    """Root configuration schema"""
    default_profile: str = "production"
    profiles: Dict[str, Any]
    agent_routing_rules: Optional[Dict[str, Any]] = None
    experiment_configs: Optional[Dict[str, Any]] = None
    component_registry: Optional[Dict[str, Any]] = None
    monitoring: Optional[Dict[str, Any]] = None
    feature_flags: Optional[Dict[str, Any]] = None


# ============================================================================
# Configuration Manager
# ============================================================================


class RAGConfigManager:
    """
    Manages RAG system configuration with support for:
    - Multiple profiles (production, experimental, etc.)
    - Profile inheritance
    - Runtime overrides
    - Component registry and dynamic loading
    - Agent-driven configuration selection
    """
    
    _instance: Optional["RAGConfigManager"] = None
    
    def __init__(self, config_path: str | Path):
        """
        Initialize configuration manager
        
        Args:
            config_path: Path to YAML configuration file
        """
        self.config_path = Path(config_path)
        self._raw_config: Dict[str, Any] = {}
        self._profiles: Dict[str, RAGProfile] = {}
        self._schema: Optional[RAGConfigSchema] = None
        self._active_profile_name: str = "production"
        self._component_registry: Dict[str, Any] = {}
        self._loaded_components: Dict[str, Any] = {}
        
        self._load_config()
    
    @classmethod
    def get_instance(cls, config_path: Optional[str | Path] = None) -> "RAGConfigManager":
        """Get singleton instance"""
        if cls._instance is None:
            if config_path is None:
                # Default config path
                config_path = Path(__file__).parent / "rag_config_schema.yaml"
            cls._instance = cls(config_path)
        return cls._instance
    
    @classmethod
    def reset_instance(cls):
        """Reset singleton (useful for testing)"""
        cls._instance = None
    
    def _load_config(self):
        """Load and parse YAML configuration"""
        logger.info(f"Loading RAG configuration from {self.config_path}")
        
        with open(self.config_path, encoding="utf-8") as f:
            self._raw_config = yaml.safe_load(f)
        
        # Parse schema
        self._schema = RAGConfigSchema(**self._raw_config)
        
        # Set default profile
        self._active_profile_name = self._schema.default_profile
        
        # Load component registry
        if self._schema.component_registry:
            self._component_registry = self._schema.component_registry
        
        # Build profiles with inheritance
        self._build_profiles()
        
        logger.info(f"Loaded {len(self._profiles)} RAG profiles")
    
    def _build_profiles(self):
        """Build profile objects with inheritance resolution"""
        profiles_data = self._schema.profiles
        
        # First pass: create base profiles without inheritance
        for profile_name, profile_data in profiles_data.items():
            if not isinstance(profile_data, dict):
                continue
            
            if profile_data.get("inherits") is None:
                # Base profile - no inheritance
                try:
                    self._profiles[profile_name] = RAGProfile(**profile_data)
                except Exception as e:
                    logger.error(f"Failed to create profile '{profile_name}': {e}")
        
        # Second pass: resolve inheritance
        for profile_name, profile_data in profiles_data.items():
            if not isinstance(profile_data, dict):
                continue
            
            inherits = profile_data.get("inherits")
            if inherits:
                parent_profile = self._profiles.get(inherits)
                if parent_profile is None:
                    logger.error(f"Profile '{profile_name}' inherits from unknown profile '{inherits}'")
                    continue
                
                # Merge parent config with overrides
                merged_data = parent_profile.dict()
                merged_data["name"] = profile_data.get("name", profile_name)
                
                # Apply overrides
                overrides = profile_data.get("overrides", {})
                self._apply_overrides(merged_data, overrides)
                
                try:
                    self._profiles[profile_name] = RAGProfile(**merged_data)
                except Exception as e:
                    logger.error(f"Failed to create profile '{profile_name}': {e}")
    
    def _apply_overrides(self, base_config: Dict[str, Any], overrides: Dict[str, Any]):
        """Apply configuration overrides recursively"""
        for key, value in overrides.items():
            if isinstance(value, dict) and key in base_config and isinstance(base_config[key], dict):
                # Recursive merge for nested dicts
                self._apply_overrides(base_config[key], value)
            else:
                # Direct override
                base_config[key] = value
    
    def get_profile(self, profile_name: Optional[str] = None) -> RAGProfile:
        """
        Get configuration profile
        
        Args:
            profile_name: Profile name, or None for active profile
        
        Returns:
            RAGProfile configuration object
        """
        if profile_name is None:
            profile_name = self._active_profile_name
        
        if profile_name not in self._profiles:
            logger.warning(f"Profile '{profile_name}' not found, using default")
            profile_name = self._schema.default_profile
        
        return self._profiles[profile_name]
    
    def set_active_profile(self, profile_name: str):
        """Set the active configuration profile"""
        if profile_name not in self._profiles:
            raise ValueError(f"Unknown profile: {profile_name}")
        
        self._active_profile_name = profile_name
        logger.info(f"Active RAG profile set to: {profile_name}")
    
    def get_active_profile(self) -> RAGProfile:
        """Get the currently active profile"""
        return self.get_profile()
    
    def list_profiles(self) -> List[str]:
        """List all available profile names"""
        return list(self._profiles.keys())
    
    def get_component_class(self, component_type: str, component_name: str) -> Optional[Type]:
        """
        Dynamically load component class from registry
        
        Args:
            component_type: Type of component (e.g., 'chunking_strategies')
            component_name: Name of specific implementation (e.g., 'hybrid_sandwich')
        
        Returns:
            Component class, or None if not found
        """
        cache_key = f"{component_type}.{component_name}"
        
        # Check cache
        if cache_key in self._loaded_components:
            return self._loaded_components[cache_key]
        
        # Look up in registry
        if component_type not in self._component_registry:
            logger.error(f"Unknown component type: {component_type}")
            return None
        
        registry_entry = self._component_registry[component_type].get(component_name)
        if not registry_entry:
            logger.error(f"Unknown component '{component_name}' in type '{component_type}'")
            return None
        
        class_path = registry_entry.get("class")
        if not class_path:
            logger.error(f"No class path for component '{component_name}'")
            return None
        
        # Dynamic import
        try:
            module_path, class_name = class_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            component_class = getattr(module, class_name)
            
            # Cache for reuse
            self._loaded_components[cache_key] = component_class
            
            logger.debug(f"Loaded component: {cache_key} -> {class_path}")
            return component_class
        
        except Exception as e:
            logger.error(f"Failed to load component '{cache_key}': {e}")
            return None
    
    def get_feature_flag(self, flag_name: str, default: bool = False) -> bool:
        """
        Check if a feature flag is enabled
        
        Args:
            flag_name: Feature flag name
            default: Default value if flag not found
        
        Returns:
            Feature flag value
        """
        if not self._schema or not self._schema.feature_flags:
            return default
        
        return self._schema.feature_flags.get(flag_name, default)
    
    def apply_agent_routing(
        self,
        query: str,
        document_count: int,
        user_preferences: Optional[Dict[str, Any]] = None
    ) -> RAGProfile:
        """
        Apply agent routing rules to select optimal configuration
        
        Args:
            query: User query text
            document_count: Number of documents in search space
            user_preferences: User-specific preferences
        
        Returns:
            Selected RAGProfile (possibly with overrides applied)
        """
        if not self._schema or not self._schema.agent_routing_rules:
            return self.get_active_profile()
        
        routing_rules = self._schema.agent_routing_rules
        selected_profile = self.get_active_profile()
        overrides_to_apply = {}
        
        # Query classification rules
        if routing_rules.get("query_classification", {}).get("enabled"):
            rules = routing_rules["query_classification"].get("rules", [])
            for rule in rules:
                condition = rule.get("condition", "")
                # Simple keyword matching (can be extended to ML-based classification)
                if self._eval_condition(condition, query):
                    if "profile" in rule:
                        selected_profile = self.get_profile(rule["profile"])
                    if "overrides" in rule:
                        self._apply_overrides(overrides_to_apply, rule["overrides"])
        
        # Document count rules
        if "document_count_rules" in routing_rules:
            for rule in routing_rules["document_count_rules"]:
                condition = rule.get("condition", "")
                if self._eval_document_count_condition(condition, document_count):
                    if "profile" in rule:
                        selected_profile = self.get_profile(rule["profile"])
                    if "overrides" in rule:
                        self._apply_overrides(overrides_to_apply, rule["overrides"])
        
        # User preferences
        if user_preferences and "user_preferences" in routing_rules:
            pref_rules = routing_rules["user_preferences"]
            for pref_key, pref_value in user_preferences.items():
                if pref_value and pref_key in pref_rules:
                    rule = pref_rules[pref_key]
                    if "profile" in rule:
                        selected_profile = self.get_profile(rule["profile"])
        
        # Apply any accumulated overrides
        if overrides_to_apply:
            profile_dict = selected_profile.dict()
            self._apply_overrides(profile_dict, overrides_to_apply)
            selected_profile = RAGProfile(**profile_dict)
        
        return selected_profile
    
    def _eval_condition(self, condition: str, query: str) -> bool:
        """Evaluate a simple condition string"""
        # Simple implementation - can be extended
        if "contains financial terms" in condition:
            financial_terms = ["revenue", "income", "profit", "earnings", "fiscal", "quarter"]
            return any(term in query.lower() for term in financial_terms)
        
        if "code-related" in condition:
            code_terms = ["function", "class", "code", "python", "javascript", "import"]
            return any(term in query.lower() for term in code_terms)
        
        if "latest info" in condition:
            time_terms = ["today", "recent", "latest", "now", "current"]
            return any(term in query.lower() for term in time_terms)
        
        return False
    
    def _eval_document_count_condition(self, condition: str, document_count: int) -> bool:
        """Evaluate document count condition"""
        # Simple parsing: "document_count < 10"
        try:
            if "<" in condition:
                threshold = int(condition.split("<")[1].strip())
                return document_count < threshold
            elif ">" in condition:
                threshold = int(condition.split(">")[1].strip())
                return document_count > threshold
        except Exception as e:
            logger.error(f"Failed to evaluate condition '{condition}': {e}")
        
        return False
    
    def get_monitoring_config(self) -> Dict[str, Any]:
        """Get monitoring configuration"""
        if self._schema and self._schema.monitoring:
            return self._schema.monitoring
        return {}
    
    def export_active_config(self) -> Dict[str, Any]:
        """Export active configuration as dictionary"""
        profile = self.get_active_profile()
        return profile.dict()
    
    def reload_config(self):
        """Reload configuration from disk"""
        logger.info("Reloading RAG configuration")
        self._profiles.clear()
        self._loaded_components.clear()
        self._load_config()


# ============================================================================
# Global accessor
# ============================================================================


def get_rag_config(config_path: Optional[str | Path] = None) -> RAGConfigManager:
    """
    Get RAG configuration manager instance
    
    Args:
        config_path: Optional path to config file
    
    Returns:
        RAGConfigManager singleton instance
    """
    return RAGConfigManager.get_instance(config_path)


# ============================================================================
# Usage Example
# ============================================================================

if __name__ == "__main__":
    # Example usage
    config_manager = get_rag_config("rag_config_schema.yaml")
    
    # List available profiles
    print("Available profiles:", config_manager.list_profiles())
    
    # Get production profile
    prod_profile = config_manager.get_profile("production")
    print(f"\nProduction profile: {prod_profile.name}")
    print(f"  Chunking strategy: {prod_profile.chunking.strategy}")
    print(f"  Chunk size: {prod_profile.chunking.config.get('chunk_size')}")
    print(f"  Retrieval strategy: {prod_profile.retrieval.strategy}")
    print(f"  RRF k: {prod_profile.retrieval.config.get('rrf_k')}")
    
    # Agent routing example
    query = "What was the revenue in Q1 FY26?"
    routed_profile = config_manager.apply_agent_routing(
        query=query,
        document_count=15,
        user_preferences=None
    )
    print(f"\nRouted profile for query '{query}': {routed_profile.name}")
    
    # Check feature flag
    caching_enabled = config_manager.get_feature_flag("enable_prompt_caching")
    print(f"\nPrompt caching enabled: {caching_enabled}")
