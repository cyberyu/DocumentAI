"use client";

import { Check, ChevronDown, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import {
	Accordion,
	AccordionContent,
	AccordionItem,
	AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";

interface EmbeddingModel {
	id: string;
	name: string;
	provider: string;
	dimensions: number;
	cost_per_million: number;
	max_tokens: number;
	description: string;
	is_local: boolean;
}

const EMBEDDING_MODELS: EmbeddingModel[] = [
	{
		id: "fastembed/all-MiniLM-L6-v2",
		name: "all-MiniLM-L6-v2",
		provider: "FastEmbed",
		dimensions: 384,
		cost_per_million: 0,
		max_tokens: 512,
		description: "Fast, lightweight local model",
		is_local: true,
	},
	{
		id: "fastembed/bge-base-en-v1.5",
		name: "bge-base-en-v1.5",
		provider: "FastEmbed",
		dimensions: 768,
		cost_per_million: 0,
		max_tokens: 512,
		description: "Balanced local model",
		is_local: true,
	},
	{
		id: "fastembed/bge-large-en-v1.5",
		name: "bge-large-en-v1.5",
		provider: "FastEmbed",
		dimensions: 1024,
		cost_per_million: 0,
		max_tokens: 512,
		description: "Best quality local model",
		is_local: true,
	},
	{
		id: "openai/text-embedding-3-small",
		name: "text-embedding-3-small",
		provider: "OpenAI",
		dimensions: 1536,
		cost_per_million: 0.02,
		max_tokens: 8191,
		description: "Affordable cloud embeddings",
		is_local: false,
	},
	{
		id: "openai/text-embedding-3-large",
		name: "text-embedding-3-large",
		provider: "OpenAI",
		dimensions: 3072,
		cost_per_million: 0.13,
		max_tokens: 8191,
		description: "Highest quality OpenAI model",
		is_local: false,
	},
	{
		id: "voyage/voyage-finance-2",
		name: "voyage-finance-2",
		provider: "Voyage AI",
		dimensions: 1024,
		cost_per_million: 0.12,
		max_tokens: 32000,
		description: "Optimized for financial documents",
		is_local: false,
	},
	{
		id: "voyage/voyage-law-2",
		name: "voyage-law-2",
		provider: "Voyage AI",
		dimensions: 1024,
		cost_per_million: 0.12,
		max_tokens: 16000,
		description: "Optimized for legal documents",
		is_local: false,
	},
	{
		id: "voyage/voyage-code-2",
		name: "voyage-code-2",
		provider: "Voyage AI",
		dimensions: 1536,
		cost_per_million: 0.12,
		max_tokens: 16000,
		description: "Optimized for code and technical docs",
		is_local: false,
	},
];

interface EmbeddingModelSelectorProps {
	selectedModels: string[];
	onSelectionChange: (models: string[]) => void;
	estimatedTokens?: number;
}

export function EmbeddingModelSelector({
	selectedModels,
	onSelectionChange,
	estimatedTokens = 10000,
}: EmbeddingModelSelectorProps) {
	const [isExpanded, setIsExpanded] = useState(false);

	// Group models by provider
	const modelsByProvider = EMBEDDING_MODELS.reduce(
		(acc, model) => {
			if (!acc[model.provider]) {
				acc[model.provider] = [];
			}
			acc[model.provider].push(model);
			return acc;
		},
		{} as Record<string, EmbeddingModel[]>
	);

	const handleModelToggle = (modelId: string) => {
		const isSelected = selectedModels.includes(modelId);

		if (isSelected) {
			// Prevent deselecting if it's the last model
			if (selectedModels.length === 1) {
				return;
			}
			onSelectionChange(selectedModels.filter((id) => id !== modelId));
		} else {
			onSelectionChange([...selectedModels, modelId]);
		}
	};

	// Calculate estimated cost
	const estimatedCost = selectedModels.reduce((total, modelId) => {
		const model = EMBEDDING_MODELS.find((m) => m.id === modelId);
		if (!model) return total;
		return total + (model.cost_per_million * estimatedTokens) / 1000000;
	}, 0);

	return (
		<Accordion
			type="single"
			collapsible
			value={isExpanded ? "embedding-models" : ""}
			onValueChange={(value) => setIsExpanded(value === "embedding-models")}
			className="w-full"
		>
			<AccordionItem
				value="embedding-models"
				className="border border-border rounded-lg"
			>
				<AccordionTrigger className="px-3 py-2.5 hover:no-underline !items-center [&>svg]:!translate-y-0">
					<div className="flex items-center gap-2 text-sm">
						<Sparkles className="h-4 w-4 text-primary" />
						<span className="font-medium">Embedding Models</span>
						<Badge variant="secondary" className="text-xs">
							{selectedModels.length} selected
						</Badge>
						{estimatedCost > 0 && (
							<span className="text-xs text-muted-foreground ml-1">
								~${estimatedCost.toFixed(4)}
							</span>
						)}
					</div>
				</AccordionTrigger>
				<AccordionContent className="px-3 pb-3">
					<div className="space-y-3">
						<p className="text-xs text-muted-foreground">
							Select one or more embedding models. Multiple models enable A/B testing and
							quality comparison without re-uploading documents.
						</p>

						{Object.entries(modelsByProvider).map(([provider, models]) => (
							<div key={provider} className="space-y-2">
								<p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
									{provider}
									{models[0].is_local && (
										<Badge variant="outline" className="ml-2 text-[10px] px-1.5 py-0">
											LOCAL • FREE
										</Badge>
									)}
								</p>
								<div className="space-y-1">
									{models.map((model) => {
										const isSelected = selectedModels.includes(model.id);
										return (
											<button
												key={model.id}
												type="button"
												onClick={() => handleModelToggle(model.id)}
												className={`w-full flex items-start gap-2.5 rounded-md border p-2.5 text-left transition-colors ${
													isSelected
														? "border-primary bg-primary/5"
														: "border-border hover:border-muted-foreground/50"
												}`}
											>
												<Checkbox
													checked={isSelected}
													className="mt-0.5"
													onCheckedChange={() => handleModelToggle(model.id)}
												/>
												<div className="flex-1 min-w-0 space-y-0.5">
													<div className="flex items-center gap-2">
														<p className="text-sm font-medium">{model.name}</p>
														{model.is_local && (
															<Badge
																variant="secondary"
																className="text-[10px] px-1.5 py-0 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300"
															>
																FREE
															</Badge>
														)}
														{!model.is_local && model.cost_per_million > 0 && (
															<span className="text-[10px] text-muted-foreground">
																${model.cost_per_million}/1M
															</span>
														)}
													</div>
													<p className="text-xs text-muted-foreground">
														{model.description} • {model.dimensions}d • {model.max_tokens.toLocaleString()} tokens
													</p>
												</div>
											</button>
										);
									})}
								</div>
							</div>
						))}

						<div className="pt-2 border-t border-border">
							<div className="flex items-center justify-between text-xs">
								<span className="text-muted-foreground">
									Estimated cost for this upload:
								</span>
								<span className="font-medium">
									{estimatedCost === 0 ? "FREE" : `$${estimatedCost.toFixed(4)}`}
								</span>
							</div>
							<p className="text-[10px] text-muted-foreground mt-1">
								Based on ~{(estimatedTokens / 1000).toFixed(0)}K tokens
							</p>
						</div>
					</div>
				</AccordionContent>
			</AccordionItem>
		</Accordion>
	);
}
