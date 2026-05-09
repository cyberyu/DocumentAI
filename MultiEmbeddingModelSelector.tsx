/**
 * Multi-Embedding Model Selector Component
 * 
 * React component for selecting embedding models during document upload.
 * Displays available models with costs, dimensions, and descriptions.
 */

import React, { useState, useEffect } from 'react';

interface EmbeddingModel {
  key: string;
  provider: string;
  dimensions: number;
  cost_per_1m_tokens: number;
  max_seq_length: number;
  description: string;
  is_free: boolean;
}

interface MultiEmbeddingModelSelectorProps {
  onSelectionChange: (selectedModels: string[]) => void;
  initialSelection?: string[];
}

export const MultiEmbeddingModelSelector: React.FC<MultiEmbeddingModelSelectorProps> = ({
  onSelectionChange,
  initialSelection = ['fastembed/bge-base-en-v1.5'], // Default to free model
}) => {
  const [availableModels, setAvailableModels] = useState<EmbeddingModel[]>([]);
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set(initialSelection));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch available models on mount
  useEffect(() => {
    fetchAvailableModels();
  }, []);

  const fetchAvailableModels = async () => {
    try {
      const response = await fetch('/api/v1/embeddings/models');
      if (!response.ok) {
        throw new Error('Failed to fetch embedding models');
      }
      const models = await response.json();
      setAvailableModels(models);
      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      setLoading(false);
    }
  };

  const toggleModel = (modelKey: string) => {
    const newSelection = new Set(selectedModels);
    if (newSelection.has(modelKey)) {
      // Don't allow deselecting if it's the last one
      if (newSelection.size === 1) {
        alert('At least one embedding model must be selected');
        return;
      }
      newSelection.delete(modelKey);
    } else {
      newSelection.add(modelKey);
    }
    setSelectedModels(newSelection);
    onSelectionChange(Array.from(newSelection));
  };

  const calculateEstimatedCost = () => {
    // Estimate: Average document = 10,000 tokens
    const avgDocTokens = 10000;
    const totalCost = Array.from(selectedModels).reduce((sum, modelKey) => {
      const model = availableModels.find(m => m.key === modelKey);
      return sum + (model ? model.cost_per_1m_tokens * avgDocTokens / 1_000_000 : 0);
    }, 0);
    return totalCost;
  };

  if (loading) {
    return <div className="text-gray-500">Loading embedding models...</div>;
  }

  if (error) {
    return <div className="text-red-500">Error: {error}</div>;
  }

  // Group models by provider
  const modelsByProvider: Record<string, EmbeddingModel[]> = {};
  availableModels.forEach(model => {
    if (!modelsByProvider[model.provider]) {
      modelsByProvider[model.provider] = [];
    }
    modelsByProvider[model.provider].push(model);
  });

  const providerLabels: Record<string, string> = {
    fastembed: 'FastEmbed (Local - FREE)',
    openai: 'OpenAI',
    voyage: 'Voyage AI',
    cohere: 'Cohere',
    google: 'Google',
    jina: 'Jina AI',
  };

  return (
    <div className="space-y-4">
      <div className="border-b pb-2">
        <h3 className="text-lg font-semibold text-gray-900">
          Select Embedding Models
        </h3>
        <p className="text-sm text-gray-600 mt-1">
          Choose one or more embedding models. Multiple models enable A/B testing and comparison.
        </p>
      </div>

      {Object.entries(modelsByProvider).map(([provider, models]) => (
        <div key={provider} className="space-y-2">
          <h4 className="text-sm font-medium text-gray-700 uppercase tracking-wider">
            {providerLabels[provider] || provider}
          </h4>
          <div className="space-y-2">
            {models.map(model => (
              <label
                key={model.key}
                className={`
                  flex items-start p-3 border rounded-lg cursor-pointer transition-colors
                  ${selectedModels.has(model.key)
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-300 bg-white'
                  }
                `}
              >
                <input
                  type="checkbox"
                  checked={selectedModels.has(model.key)}
                  onChange={() => toggleModel(model.key)}
                  className="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                />
                <div className="ml-3 flex-1">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-900">
                      {model.key.split('/')[1]}
                    </span>
                    <div className="flex items-center space-x-2">
                      {model.is_free && (
                        <span className="px-2 py-0.5 text-xs font-semibold text-green-700 bg-green-100 rounded-full">
                          FREE
                        </span>
                      )}
                      <span className="text-xs text-gray-500">
                        {model.dimensions} dims
                      </span>
                    </div>
                  </div>
                  <p className="text-xs text-gray-600 mt-0.5">
                    {model.description}
                  </p>
                  {!model.is_free && (
                    <p className="text-xs text-gray-500 mt-1">
                      Cost: ${model.cost_per_1m_tokens}/1M tokens • Max: {model.max_seq_length} tokens
                    </p>
                  )}
                </div>
              </label>
            ))}
          </div>
        </div>
      ))}

      <div className="border-t pt-3 mt-4">
        <div className="flex items-center justify-between">
          <div className="text-sm text-gray-700">
            <span className="font-medium">{selectedModels.size}</span> model{selectedModels.size !== 1 ? 's' : ''} selected
          </div>
          <div className="text-sm text-gray-700">
            Estimated cost: 
            <span className="font-semibold ml-1">
              ${calculateEstimatedCost().toFixed(4)}
            </span>
            <span className="text-gray-500 ml-1">per document</span>
          </div>
        </div>
        {selectedModels.size > 1 && (
          <p className="text-xs text-blue-600 mt-2">
            💡 Multiple models enable retrieval comparison and A/B testing
          </p>
        )}
      </div>
    </div>
  );
};


/**
 * Upload Form with Multi-Embedding Support
 * 
 * Integrates model selector into document upload flow.
 */

interface UploadFormWithMultiEmbeddingProps {
  searchSpaceId: number;
  onUploadSuccess: (response: any) => void;
  onUploadError: (error: string) => void;
}

export const UploadFormWithMultiEmbedding: React.FC<UploadFormWithMultiEmbeddingProps> = ({
  searchSpaceId,
  onUploadSuccess,
  onUploadError,
}) => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedModels, setSelectedModels] = useState<string[]>(['fastembed/bge-base-en-v1.5']);
  const [uploading, setUploading] = useState(false);
  const [showModelSelector, setShowModelSelector] = useState(false);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (files && files.length > 0) {
      setSelectedFile(files[0]);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      alert('Please select a file');
      return;
    }

    if (selectedModels.length === 0) {
      alert('Please select at least one embedding model');
      return;
    }

    setUploading(true);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('search_space_id', searchSpaceId.toString());
      formData.append('embedding_models', JSON.stringify(selectedModels));
      formData.append('should_summarize', 'false');
      formData.append('use_vision_llm', 'false');
      formData.append('processing_mode', 'basic');

      const response = await fetch('/api/v1/documents/fileupload-multi-embed', {
        method: 'POST',
        body: formData,
        headers: {
          'Authorization': `Bearer ${getAuthToken()}`, // Get from your auth system
        },
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Upload failed');
      }

      const result = await response.json();
      onUploadSuccess(result);
      
      // Reset form
      setSelectedFile(null);
      setShowModelSelector(false);
    } catch (error) {
      onUploadError(error instanceof Error ? error.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* File selector */}
      <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-gray-400 transition-colors">
        <input
          type="file"
          onChange={handleFileChange}
          accept=".pdf,.docx,.txt,.md"
          className="hidden"
          id="file-upload"
        />
        <label htmlFor="file-upload" className="cursor-pointer">
          {selectedFile ? (
            <div>
              <p className="text-sm font-medium text-gray-900">{selectedFile.name}</p>
              <p className="text-xs text-gray-500 mt-1">
                {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
              </p>
            </div>
          ) : (
            <div>
              <p className="text-sm text-gray-600">Click to select file</p>
              <p className="text-xs text-gray-500 mt-1">PDF, DOCX, TXT, MD</p>
            </div>
          )}
        </label>
      </div>

      {/* Embedding model selector toggle */}
      <div>
        <button
          type="button"
          onClick={() => setShowModelSelector(!showModelSelector)}
          className="text-sm font-medium text-blue-600 hover:text-blue-700 flex items-center"
        >
          {showModelSelector ? '▼' : '▶'} Advanced: Select Embedding Models
          <span className="ml-2 text-gray-500">
            ({selectedModels.length} selected)
          </span>
        </button>
        
        {showModelSelector && (
          <div className="mt-3 border rounded-lg p-4 bg-gray-50">
            <MultiEmbeddingModelSelector
              onSelectionChange={setSelectedModels}
              initialSelection={selectedModels}
            />
          </div>
        )}
      </div>

      {/* Upload button */}
      <button
        onClick={handleUpload}
        disabled={!selectedFile || uploading}
        className={`
          w-full py-2 px-4 rounded-lg font-medium text-white transition-colors
          ${!selectedFile || uploading
            ? 'bg-gray-400 cursor-not-allowed'
            : 'bg-blue-600 hover:bg-blue-700'
          }
        `}
      >
        {uploading ? 'Uploading...' : 'Upload Document'}
      </button>

      {uploading && (
        <p className="text-sm text-gray-600 text-center">
          Generating embeddings with {selectedModels.length} model{selectedModels.length !== 1 ? 's' : ''}...
        </p>
      )}
    </div>
  );
};

// Helper function - integrate with your auth system
function getAuthToken(): string {
  // Get JWT from cookie or localStorage
  const match = document.cookie.match(/jwt=([^;]+)/);
  return match ? match[1] : '';
}

export default MultiEmbeddingModelSelector;
