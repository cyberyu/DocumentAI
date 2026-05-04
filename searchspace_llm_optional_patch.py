"""
Patch to make LLM configuration optional for search spaces.
This allows document uploads without requiring LLM setup first.

Mount this file to override search space validation.
"""
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base


class SearchSpacesPatch:
    """
    Patch for SearchSpaces model to set default agent_llm_id.
    
    This ensures search spaces always have a valid LLM ID, even if not explicitly set.
    Default to -1 which is typically the first/default LLM in global_llm_config.yaml.
    """
    
    @staticmethod
    def get_default_agent_llm_id():
        """Return default LLM ID for search spaces"""
        return -1  # First LLM in global_llm_config.yaml
    
    @staticmethod
    def patch_search_space_creation(search_space_data: dict) -> dict:
        """
        Patch search space creation data to include default agent_llm_id.
        
        Args:
            search_space_data: Dictionary with search space fields
            
        Returns:
            Patched dictionary with agent_llm_id set if missing
        """
        if 'agent_llm_id' not in search_space_data or search_space_data['agent_llm_id'] is None:
            search_space_data['agent_llm_id'] = SearchSpacesPatch.get_default_agent_llm_id()
            print(f"🔧 Auto-set agent_llm_id={search_space_data['agent_llm_id']} for search space")
        
        return search_space_data
    
    @staticmethod
    def validate_for_document_upload(search_space) -> tuple[bool, str]:
        """
        Validate search space for document upload.
        
        Documents can be uploaded WITHOUT LLM configuration.
        LLM is only needed for chat/query operations.
        
        Args:
            search_space: SearchSpace model instance
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Always allow document uploads
        return True, ""
    
    @staticmethod
    def validate_for_chat(search_space) -> tuple[bool, str]:
        """
        Validate search space for chat operations.
        
        Chat requires an LLM to be configured.
        
        Args:
            search_space: SearchSpace model instance
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if search_space.agent_llm_id is None:
            return False, "Please configure an LLM for this search space to enable chat"
        return True, ""


# Make validation always pass for document uploads
REQUIRE_LLM_FOR_DOCUMENT_UPLOAD = False
REQUIRE_LLM_FOR_CHAT = True

# Default LLM ID to use when none is set
DEFAULT_AGENT_LLM_ID = -1

print("✅ Search space LLM requirement patch loaded")
print(f"   - Document upload requires LLM: {REQUIRE_LLM_FOR_DOCUMENT_UPLOAD}")
print(f"   - Chat requires LLM: {REQUIRE_LLM_FOR_CHAT}")
print(f"   - Default agent_llm_id: {DEFAULT_AGENT_LLM_ID}")
