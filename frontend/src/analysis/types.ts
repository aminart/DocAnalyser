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
  warnings: string[]; // parties non lues (pages scannées, slides sans texte…)
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
  found?: boolean; // false : le repère cité n'existe pas dans le document
}

/** Demande d'affichage d'un passage d'origine dans le panneau « Source ». */
export interface SourceRequest {
  document: string; // vide : recherche dans tous les documents de l'analyse
  location: string;
  text: string; // propos à vérifier (point clé ou verbatim)
}

export interface SourcePassage {
  document: string;
  location: string;
  found: boolean;
  nearest: boolean;
  lines: { ref: string; text: string; hit: boolean }[];
}

/** Vérification d'un verbatim dans le texte réel des documents. */
export type QuoteCheck = 'exact' | 'close' | 'absent' | '';

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
  quote_check: QuoteCheck;
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

/** Présent quand le corpus dépassait la fenêtre du modèle et a été analysé par lots. */
export interface Coverage {
  batches: number;
  items: number;
  unassigned: number;
  recovered: number; // éléments non repris par la rédaction, rajoutés tels qu'extraits
}

export interface ThemesResult {
  kind: 'themes';
  title: string;
  brief: string;
  themes: Theme[];
  actions: ActionItem[];
  sources: SourceCount[];
  stats: { themes: number; points: number; quotes: number; quotes_exact: number; actions: number };
  coverage?: Coverage | null;
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
  id: string;
  label: string;
  type: 'entry' | 'step' | 'decision' | 'exit' | 'goal';
  friction: boolean;
}

export interface FlowEdge {
  from: string;
  to: string;
  label: string;
  kind: 'main' | 'alt' | 'exit' | 'loop';
}

/** Graphe libre reconstitué depuis les documents ; « mermaid » est généré par le backend. */
export interface FlowGraph {
  nodes: FlowNode[];
  edges: FlowEdge[];
  mermaid: string;
}

export interface Priority {
  severity: 'Bloquant' | 'Majeur' | 'Mineur';
  title: string;
  body: string;
  quote: string;
  quote_check: QuoteCheck;
  phase: string;
  frequency: string;
}

export interface JourneyResult {
  kind: 'journey';
  title: string;
  brief: string;
  phases: JourneyPhase[];
  flow: FlowGraph;
  priorities: Priority[];
  extra: { text: string; document: string; location: string }[];
  sources: SourceCount[];
  coverage?: Coverage | null;
}

/** Ligne de l'historique. */
export interface AnalysisSummary {
  id: string;
  title: string;
  status: AnalysisStatus;
  mode: AnalysisMode;
  mode_label: string;
  level_label: string;
  model_name: string;
  documents: string[];
  created_at: string;
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
  questions?: Question[];
}

/** Question posée sur les documents d'une analyse (réponse sourcée, rédigée au fil de l'eau). */
export interface Question {
  id: string;
  question: string;
  answer: string;
  status: 'running' | 'done' | 'failed';
  error: string | null;
  sources: SourceRef[];
  /** full : corpus envoyé en entier ; search : passages choisis par la recherche par mots-clés. */
  scope: 'full' | 'search' | '';
  passages: number;
  keywords: string[];
  model_name: string;
  created_at: string;
}

/* ---------- Réglages : connexions aux modèles ---------- */

export type ConnectionKind = 'openai' | 'gemini' | 'anthropic';

export interface ConnectionTest {
  ok: boolean;
  /** Champ en cause : api_base, api_key, certificate, models. */
  field: string | null;
  title: string;
  message: string;
  at: string;
  /** Modèles proposés par le serveur (null s'il ne les liste pas). */
  available?: string[] | null;
  missing?: string[];
}

export interface Connection {
  id: string;
  /** app : enregistrée depuis l'écran ; env : déclarée dans le fichier .env (lecture seule). */
  source: 'app' | 'env';
  env_prefix?: string;
  kind: ConnectionKind;
  kind_label: string;
  name: string;
  api_base: string;
  has_api_key: boolean;
  api_key_hint: string;
  certificate: { name: string; imported_at?: string; expires_at?: string } | null;
  models: string[];
  context_tokens: number;
  max_output_tokens: number;
  last_test: ConnectionTest | null;
}

export interface ConnectionsState {
  connections: Connection[];
  env_file: string | null;
  storage_dir: string;
  created?: string;
}

export interface ConnectionForm {
  kind: ConnectionKind;
  name: string;
  api_base: string;
  /** null : garder la clé enregistrée. */
  api_key: string | null;
  models: string[];
  context_tokens: number | null;
}
