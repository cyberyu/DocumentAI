"use client";

import { useAtomValue, useSetAtom } from "jotai";
import { AlertTriangle } from "lucide-react";
import { useRouter } from "next/navigation";
import {
	createContext,
	type FC,
	type ReactNode,
	useCallback,
	useContext,
	useRef,
	useState,
} from "react";
import {
	globalNewLLMConfigsAtom,
	llmPreferencesAtom,
} from "@/atoms/new-llm-config/new-llm-config-query.atoms";
import { activeSearchSpaceIdAtom } from "@/atoms/search-spaces/search-space-query.atoms";
import { searchSpaceSettingsDialogAtom } from "@/atoms/settings/settings-dialog.atoms";
import { DocumentUploadTab } from "@/components/sources/DocumentUploadTab";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";

// Context for opening the dialog from anywhere
interface DocumentUploadDialogContextType {
	openDialog: () => void;
	closeDialog: () => void;
}

const DocumentUploadDialogContext = createContext<DocumentUploadDialogContextType | null>(null);

const NOOP_DIALOG: DocumentUploadDialogContextType = {
	openDialog: () => {},
	closeDialog: () => {},
};

export const useDocumentUploadDialog = (): DocumentUploadDialogContextType => {
	const context = useContext(DocumentUploadDialogContext);
	return context ?? NOOP_DIALOG;
};

// Provider component
export const DocumentUploadDialogProvider: FC<{ children: ReactNode }> = ({ children }) => {
	const [isOpen, setIsOpen] = useState(false);
	const isClosingRef = useRef(false);

	const openDialog = useCallback(() => {
		// Prevent opening if we just closed (debounce)
		if (isClosingRef.current) {
			return;
		}
		setIsOpen(true);
	}, []);

	const closeDialog = useCallback(() => {
		isClosingRef.current = true;
		setIsOpen(false);
		// Reset the flag after a short delay to allow for file picker to close
		setTimeout(() => {
			isClosingRef.current = false;
		}, 300);
	}, []);

	const handleOpenChange = useCallback(
		(open: boolean) => {
			if (!open) {
				// Only close if not already in closing state
				if (!isClosingRef.current) {
					closeDialog();
				}
			} else {
				// Only open if not in the middle of closing
				if (!isClosingRef.current) {
					setIsOpen(true);
				}
			}
		},
		[closeDialog]
	);

	return (
		<DocumentUploadDialogContext.Provider value={{ openDialog, closeDialog }}>
			{children}
			<DocumentUploadPopupContent isOpen={isOpen} onOpenChange={handleOpenChange} />
		</DocumentUploadDialogContext.Provider>
	);
};

// Internal component that renders the dialog
const DocumentUploadPopupContent: FC<{
	isOpen: boolean;
	onOpenChange: (open: boolean) => void;
}> = ({ isOpen, onOpenChange }) => {
	const searchSpaceId = useAtomValue(activeSearchSpaceIdAtom);
	const setSearchSpaceSettingsDialog = useSetAtom(searchSpaceSettingsDialogAtom);
	const { data: preferences = {}, isFetching: preferencesLoading } =
		useAtomValue(llmPreferencesAtom);
	const { data: globalConfigs = [], isFetching: globalConfigsLoading } =
		useAtomValue(globalNewLLMConfigsAtom);
	const router = useRouter();

	if (!searchSpaceId) return null;

	const handleSuccess = () => {
		onOpenChange(false);
	};

	// Check if document summary LLM is properly configured
	// - If ID is 0 (Auto mode), we need global configs to be available
	// - If ID is positive (user config) or negative (specific global config), it's configured
	// - If ID is null/undefined, it's not configured
	const docSummaryLlmId = preferences.document_summary_llm_id;
	const isAutoMode = docSummaryLlmId === 0;
	const hasGlobalConfigs = globalConfigs.length > 0;

	const hasDocumentSummaryLLM =
		docSummaryLlmId !== null &&
		docSummaryLlmId !== undefined &&
		// If it's Auto mode, we need global configs to actually be available
		(!isAutoMode || hasGlobalConfigs);

	const isLoading = preferencesLoading || globalConfigsLoading;

	return (
		<Dialog open={isOpen} onOpenChange={onOpenChange}>
			<DialogContent
				onPointerDownOutside={(e) => e.preventDefault()}
				onInteractOutside={(e) => e.preventDefault()}
				onEscapeKeyDown={(e) => e.preventDefault()}
				className="select-none max-w-[1400px] w-[98vw] sm:w-[1280px] h-[min(650px,90dvh)] sm:h-[min(820px,92vh)] flex flex-col p-0 gap-0 overflow-hidden border border-border ring-0 bg-muted dark:bg-muted text-foreground [&>button]:right-3 sm:[&>button]:right-6 [&>button]:top-5 sm:[&>button]:top-8 [&>button]:opacity-80 [&>button]:hover:opacity-100 [&>button]:hover:bg-foreground/10 [&>button]:z-[100] [&>button>svg]:size-4 sm:[&>button>svg]:size-5"
			>
				<div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
					<DialogHeader className="sticky top-0 z-20 bg-muted px-4 sm:px-6 pt-6 sm:pt-8 pb-10">
						<DialogTitle className="text-xl sm:text-3xl font-semibold tracking-tight pr-8 sm:pr-0">
							Upload Documents
						</DialogTitle>
						<DialogDescription className="text-xs sm:text-base text-muted-foreground/80 line-clamp-1">
							Upload and sync your documents to your search space
						</DialogDescription>
						<div className="pt-2">
							<Button
								variant="outline"
								size="sm"
								onClick={() => {
									onOpenChange(false);
									router.push(`/dashboard/${searchSpaceId}/benchmark`);
								}}
							>
								Benchmark
							</Button>
						</div>
					</DialogHeader>

					<div className="px-4 sm:px-6 pb-4 sm:pb-6">
						{!isLoading && !hasDocumentSummaryLLM && (
							<Alert
								className="mb-4 rounded-xl border-amber-500/40 bg-amber-500/10 text-amber-200 [&>svg]:text-amber-400"
							>
								<AlertTriangle className="h-4 w-4" />
								<AlertTitle className="text-amber-200">AI Summary unavailable</AlertTitle>
								<AlertDescription className="mt-1 text-amber-300/80">
									No LLM configured — AI Summary is disabled. You can still upload and generate pipeline variants.{" "}
									<button
										type="button"
										className="underline underline-offset-2 hover:text-amber-200 transition-colors"
										onClick={() => {
											onOpenChange(false);
											setSearchSpaceSettingsDialog({
												open: true,
												initialTab: "models",
											});
										}}
									>
										Configure in Settings
									</button>
								</AlertDescription>
							</Alert>
						)}
						<DocumentUploadTab searchSpaceId={searchSpaceId} onSuccess={handleSuccess} />
					</div>
				</div>
			</DialogContent>
		</Dialog>
	);
};
