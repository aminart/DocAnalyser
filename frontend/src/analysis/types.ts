export type AnalysisMode = 'global' | 'transcript' | 'notes' | 'flow';
export type AnalysisLevel = 'synth' | 'detail' | 'deep';
export type AnalysisStatus = 'running' | 'done' | 'failed' | 'cancelled';

export interface ModelInfo {
  id: string;
  name: string;
  provider: string; // préfixe .env du fournisseur (CUSTOM_LLM, CUSTOM_LLM_2)
  provider_label: string;
  description: string;
  quality: number;
  speed: number;
  economy: number;
  tier: 'deep' | 'balanced' | 'fast';
  configured: boolean;
}

export interface UploadedDocument {
  id: string;
  name: string;
  ext: string;
  size_bytes: number;
  units: string;
  pages: number;
}

export interface AnalysisStep {
  key: string;
  label: string;
  detail: string;
  state: 'done' | 'active' | 'pending';
  progress: number;
}

export interface SourceRef {
  document: string;
  location: string;
}

export interface ThemePoint {
  lead: string;
  body: string;
  sources: SourceRef[];
}

export interface Theme {
  title: string;
  summary: string;
  documents: string[];
  points: ThemePoint[];
  quote: string;
  quote_by: string;
  nuance: string;
}

export interface ActionItem {
  title: string;
  body: string;
  theme: number | null;
}

export interface SourceCount {
  document: string;
  citations: number;
}

export interface ThemesResult {
  kind: 'themes';
  title: string;
  brief: string;
  themes: Theme[];
  actions: ActionItem[];
  sources: SourceCount[];
  stats: { themes: number; points: number; quotes: number; actions: number };
}

export interface JourneyPhase {
  name: string;
  mood: string;
  sentiment: number; // -2 … 2
  does: string;
  touchpoints: string[];
  frictions: string[];
  opportunities: string[];
}

export interface FlowNode {
  label: string;
  kind: 'entry' | 'step' | 'goal';
  breaking: boolean;
  exit: string;
}

export interface Priority {
  severity: 'Bloquant' | 'Majeur' | 'Mineur';
  title: string;
  body: string;
  quote: string;
  phase: string;
  frequency: string;
}

export interface JourneyResult {
  kind: 'journey';
  title: string;
  brief: string;
  phases: JourneyPhase[];
  flow: FlowNode[];
  priorities: Priority[];
  sources: SourceCount[];
}

export interface Analysis {
  id: string;
  status: AnalysisStatus;
  progress: number;
  steps: AnalysisStep[];
  preview: string[];
  title: string;
  mode: AnalysisMode;
  mode_label: string;
  level: AnalysisLevel;
  level_label: string;
  model_id: string;
  model_name: string;
  model_fallback: boolean;
  language: 'fr' | 'en';
  cite: boolean;
  documents: UploadedDocument[];
  created_at: string;
  result: ThemesResult | JourneyResult | null;
  markdown: string;
  error: string | null;
}
