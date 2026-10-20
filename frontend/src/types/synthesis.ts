export type SynthesisMode =
  | 'global_summary'
  | 'transcript_summary'
  | 'user_journey'
  | 'raw_notes';

export type JobStage =
  | 'uploading'
  | 'parsing'
  | 'analyzing'
  | 'ready'
  | 'failed';

export type ExportFormat = 'md' | 'docx' | 'pdf';

export interface SourceReference {
  file_name: string;
  location: string;
  excerpt: string;
}

// Mode 1 : Synthèse Documentaire Globale
export interface StructuredParagraph {
  heading: string;
  body: string;
  sources: SourceReference[];
}

export interface ThemeItem {
  theme: string;
  summary: string;
  arguments: string[];
  sources: SourceReference[];
}

export interface MetricItem {
  label: string;
  value: string;
  context: string;
  trend: 'up' | 'down' | 'neutral';
  sources: SourceReference[];
}

export interface RecommendationItem {
  title: string;
  description: string;
  priority: 'Haute' | 'Moyenne' | 'Basse';
  sources: SourceReference[];
}

export interface GlobalSummaryResult {
  mode: 'global_summary';
  title: string;
  executive_summary: string;
  executive_paragraphs?: StructuredParagraph[];
  key_themes: ThemeItem[];
  key_metrics: MetricItem[];
  recommendations: RecommendationItem[];
}

// Mode 2 : Synthèse de Transcription
export interface ParticipantItem {
  name: string;
  role: string;
}

export interface TranscriptClusterItem {
  tag: string;
  consolidated_notes: string;
  key_takeaways: string[];
  sources: SourceReference[];
}

export interface DecisionItem {
  decision: string;
  rationale: string;
  sources: SourceReference[];
}

export interface ActionItem {
  task: string;
  assignee: string;
  due_date: string;
  priority: 'Haute' | 'Moyenne' | 'Basse';
  sources: SourceReference[];
}

export interface TensionItem {
  topic: string;
  description: string;
  stakeholders: string[];
  sources: SourceReference[];
}

export interface TranscriptSummaryResult {
  mode: 'transcript_summary';
  title: string;
  context: string;
  participants: ParticipantItem[];
  agenda: string[];
  thematic_clusters: TranscriptClusterItem[];
  decisions_made: DecisionItem[];
  action_items: ActionItem[];
  open_questions_and_tensions: TensionItem[];
}

// Mode 3 : Extraction des Parcours Utilisateurs
export interface PersonaItem {
  name: string;
  profile: string;
  goals: string[];
  frustrations: string[];
  sources: SourceReference[];
}

export interface UserJourneyStep {
  step_number: number;
  stage: string;
  persona: string;
  action: string;
  user_goal: string;
  touchpoint: string;
  pain_points: string[];
  opportunities: string[];
  sources: SourceReference[];
}

export interface UserJourneyResult {
  mode: 'user_journey';
  title: string;
  overview: string;
  personas: PersonaItem[];
  steps: UserJourneyStep[];
  mermaid_diagram: string;
}

// Mode 4 : Synthèse de Notes en Vrac
export interface ConsolidatedIdea {
  title: string;
  structured_content: string;
  merged_count: number;
  sources: SourceReference[];
}

export interface NoteCluster {
  pillar: string;
  tags: string[];
  summary: string;
  consolidated_ideas: ConsolidatedIdea[];
}

export interface NextStepItem {
  action: string;
  category: string;
  impact: 'Élevé' | 'Moyen' | 'Faible';
  sources: SourceReference[];
}

export interface RawNotesResult {
  mode: 'raw_notes';
  title: string;
  deduplication_summary: string;
  clusters: NoteCluster[];
  suggested_next_steps: NextStepItem[];
}

export type SynthesisPayload =
  | GlobalSummaryResult
  | TranscriptSummaryResult
  | UserJourneyResult
  | RawNotesResult;

export interface DocumentMetadata {
  document_id: string;
  file_name: string;
  mime_type: string;
  total_size_bytes: number;
  uploaded_chunks: number;
  total_chunks: number;
  storage_key: string;
  is_complete: boolean;
}

export interface DocumentPreviewBlock {
  location: string;
  content: string;
}

export interface DocumentPreviewResponse {
  document_id: string;
  file_name: string;
  total_blocks: number;
  blocks: DocumentPreviewBlock[];
}

export interface JobStatusResponse {
  job_id: string;
  stage: JobStage;
  progress_percent: number;
  current_step_detail: string;
  mode: SynthesisMode;
  model_name: string;
  documents: DocumentMetadata[];
  created_at: string;
  updated_at: string;
  error_message?: string | null;
  result?: SynthesisPayload | null;
}

export interface ModelOption {
  id: string;
  provider?: 'gemini' | 'mistral' | 'custom';
  provider_label?: string;
  label: string;
  description: string;
  context_window: number;
  api_key_configured?: boolean;
}
