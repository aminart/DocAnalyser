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
  /** Modèle choisi pour DocAnalyser dans Studio Dock : proposé d'office. */
  preferred?: boolean;
  /** Modèle sur ce poste (Ollama, LM Studio…) : bien plus lent qu'un modèle en ligne. */
  local?: boolean;
}

export interface UploadedDocument {
  id: string;
  name: string;
  ext: string;
  size_bytes: number;
  units: string;
  pages: number;
  warnings: string[]; // parties non lues (pages scannées, slides sans texte…)
  /** Le document se découpe en pages (PDF) ou slides (PowerPoint) qu'on peut choisir d'analyser. */
  sections?: 'pages' | 'slides' | null;
  last_section?: number;
  /** Images à lire par un modèle qui voit les images (pages scannées, schémas, photos). */
  images?: number;
  /** Aucun texte : le document n'est analysé qu'avec un modèle de vision. */
  images_only?: boolean;
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
  /** Thème réécrit par « Approfondir ce thème » ; previous : version d'avant, pour y revenir. */
  deepened?: boolean;
  previous?: Theme;
  /** Remarque sur la rédaction (éléments repris tels qu'extraits). */
  note?: string;
  /** Synthèse courte d'un gros document : tous les éléments extraits du thème, en annexe. */
  details?: ThemeDetail[];
}

export interface ThemeDetail {
  text: string;
  kind: string;
  document: string;
  location: string;
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
  short?: boolean; // synthèse courte : longueur bornée, le détail complet en annexe
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

export interface ModelActivity {
  phase: 'reading' | 'writing';
  /** Secondes depuis l'envoi de la demande. */
  seconds: number;
  /** Caractères de réponse reçus. */
  chars: number;
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
  /** Texte exporté modifié à la main après l'analyse. */
  markdown_edited?: boolean;
  /** Modèle qui a lu les images des documents ; vide = texte seul. */
  vision_model_id?: string;
  /** Gros documents : tout rédigé plutôt qu'une synthèse courte. */
  full_length?: boolean;
  /** Durée restante estimée (secondes), mesurée sur les premiers lots ; null si inconnue. */
  eta_seconds?: number | null;
  /** Appel au modèle en cours : il lit la demande (rien reçu) ou il écrit ; null si aucun. */
  activity?: ModelActivity | null;
  error: string | null;
  /** L'échec se corrige dans les Réglages (clé refusée, adresse manquante ou injoignable, modèle absent). */
  error_settings?: boolean;
  questions?: Question[];
  /** Thème en cours d'approfondissement, ou dont l'approfondissement a échoué ; null si aucun. */
  deepening?: Deepening | null;
}

export interface Deepening {
  theme: number;
  title: string;
  status: 'running' | 'failed';
  error: string | null;
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
  /** app : enregistrée depuis l'écran ; env : déclarée dans le fichier .env ; studiodock : réglée dans Studio Dock
   * (Réglages › Modèles d'IA). Les deux dernières sont en lecture seule. */
  source: 'app' | 'env' | 'studiodock';
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
  /** Studio Dock laisse à DocAnalyser sa configuration propre. */
  studiodock_own?: boolean;
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
