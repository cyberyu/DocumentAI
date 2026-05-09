"""
Embedding configuration models for config-driven adapter selection.

Provides structured configuration for single and multi-model embedding.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class SingleEmbeddingConfig:
    """Configuration for single embedding model."""
    provider: str  # "openai", "fastembed", "voyage", etc.
    model: str  # Model name
    api_key: Optional[str] = None
    dimensions: Optional[int] = None
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiEmbeddingConfig:
    """Configuration for multiple embedding models."""
    models: List[SingleEmbeddingConfig]
    parallel: bool = True  # Generate embeddings in parallel
    
    @classmethod
    def from_model_keys(cls, model_keys: List[str]) -> "MultiEmbeddingConfig":
        """
        Create config from model keys like ["openai/text-embedding-3-large", "fastembed/bge-small-en-v1.5"].
        
        Args:
            model_keys: List of "provider/model" strings
            
        Returns:
            MultiEmbeddingConfig with parsed models
        """
        models = []
        for key in model_keys:
            if "/" in key:
                provider, model = key.split("/", 1)
            else:
                # Fallback: assume it's a provider
                provider = key
                model = "default"
            
            models.append(SingleEmbeddingConfig(
                provider=provider,
                model=model
            ))
        
        return cls(models=models)
    
    def to_model_keys(self) -> List[str]:
        """Convert back to model keys for storage."""
        return [f"{m.provider}/{m.model}" for m in self.models]


@dataclass
class EmbeddingConfig:
    """
    Top-level embedding configuration.
    
    Can represent either single or multi-model configuration.
    """
    mode: str = "single"  # "single" or "multi"
    single: Optional[SingleEmbeddingConfig] = None
    multi: Optional[MultiEmbeddingConfig] = None
    
    @classmethod
    def from_model_list(cls, model_keys: Optional[List[str]] = None) -> "EmbeddingConfig":
        """
        Create EmbeddingConfig from optional model list.
        
        Args:
            model_keys: None or list of model keys
                - None: Use default single embedding
                - [one_model]: Single embedding with that model
                - [model1, model2, ...]: Multi-embedding
        
        Returns:
            EmbeddingConfig configured for single or multi mode
        """
        if not model_keys:
            # Default: single embedding (use system default)
            return cls(
                mode="single",
                single=SingleEmbeddingConfig(provider="default", model="default")
            )
        
        if len(model_keys) == 1:
            # Single model
            provider, model = model_keys[0].split("/", 1) if "/" in model_keys[0] else (model_keys[0], "default")
            return cls(
                mode="single",
                single=SingleEmbeddingConfig(provider=provider, model=model)
            )
        
        # Multiple models
        return cls(
            mode="multi",
            multi=MultiEmbeddingConfig.from_model_keys(model_keys)
        )
    
    def is_multi(self) -> bool:
        """Check if this is multi-model configuration."""
        return self.mode == "multi" and self.multi is not None
    
    def get_model_keys(self) -> List[str]:
        """Get list of model keys for storage/processing."""
        if self.mode == "multi" and self.multi:
            return self.multi.to_model_keys()
        elif self.mode == "single" and self.single:
            return [f"{self.single.provider}/{self.single.model}"]
        return []
