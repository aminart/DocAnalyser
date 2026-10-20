from __future__ import annotations

import io
import re
from docx import Document as DocxDocument
from fpdf import FPDF

from app.schemas.models import (
    ExportFormat,
    GlobalSummaryResult,
    RawNotesResult,
    SourceReference,
    SynthesisPayload,
    TranscriptSummaryResult,
    UserJourneyResult,
)


class SynthesisExportService:
    """Génère les exports Markdown (.md), Word (.docx) et PDF (.pdf) avec citations sources."""

    def export(self, payload: SynthesisPayload, fmt: ExportFormat) -> tuple[bytes, str, str]:
        safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", payload.title.lower()).strip("_") or "synthese"
        md_text = self.to_markdown(payload)

        if fmt == ExportFormat.MARKDOWN:
            return (
                md_text.encode("utf-8"),
                "text/markdown; charset=utf-8",
                f"{safe_slug}.md",
            )
        if fmt == ExportFormat.DOCX:
            return (
                self._markdown_to_docx(payload.title, md_text),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                f"{safe_slug}.docx",
            )
        return (
            self._markdown_to_pdf(payload.title, md_text),
            "application/pdf",
            f"{safe_slug}.pdf",
        )

    def _format_sources(self, sources: list[SourceReference]) -> str:
        if not sources:
            return ""
        refs = [f"`{s.file_name} — {s.location}`" for s in sources]
        return " *(Sources : " + ", ".join(refs) + ")*"

    def to_markdown(self, payload: SynthesisPayload) -> str:
        lines: list[str] = [f"# {payload.title}", ""]

        if isinstance(payload, GlobalSummaryResult):
            lines.append("## 1. Synthèse Exécutive Structurée")
            lines.append(payload.executive_summary)
            lines.append("")
            for para in payload.executive_paragraphs:
                lines.append(f"### {para.heading}")
                lines.append(f"{para.body}{self._format_sources(para.sources)}")
                lines.append("")

            lines.append("## 2. Métriques & Chiffres Clés")
            for m in payload.key_metrics:
                lines.append(
                    f"- **{m.label}** : **{m.value}** — {m.context}{self._format_sources(m.sources)}"
                )
            lines.append("")

            lines.append("## 3. Thématiques Clés & Arguments")
            for t in payload.key_themes:
                lines.append(f"### {t.theme}")
                lines.append(t.summary)
                for arg in t.arguments:
                    lines.append(f"  - {arg}")
                lines.append(self._format_sources(t.sources))
                lines.append("")

            lines.append("## 4. Recommandations")
            for r in payload.recommendations:
                lines.append(
                    f"- **[{r.priority}] {r.title}** : {r.description}{self._format_sources(r.sources)}"
                )

        elif isinstance(payload, TranscriptSummaryResult):
            lines.append("## 1. Contexte & Participants")
            lines.append(payload.context)
            lines.append("")
            for p in payload.participants:
                lines.append(f"- **{p.name}** ({p.role})")
            lines.append("")

            lines.append("## 2. Décisions Actées")
            for d in payload.decisions_made:
                lines.append(f"- **{d.decision}** — {d.rationale}{self._format_sources(d.sources)}")
            lines.append("")

            lines.append("## 3. Plan d'Action")
            for a in payload.action_items:
                lines.append(
                    f"- **[ ] {a.task}** | Responsable : `{a.assignee}` | Échéance : `{a.due_date}` ({a.priority}){self._format_sources(a.sources)}"
                )
            lines.append("")

            lines.append("## 4. Synthèse Thématique")
            for c in payload.thematic_clusters:
                lines.append(f"### {c.tag}")
                lines.append(c.consolidated_notes)
                for k in c.key_takeaways:
                    lines.append(f"  - {k}")
                lines.append(self._format_sources(c.sources))
                lines.append("")

            if payload.open_questions_and_tensions:
                lines.append("## 5. Points de Tension & Questions en Suspens")
                for t in payload.open_questions_and_tensions:
                    lines.append(f"- **{t.topic}** : {t.description}{self._format_sources(t.sources)}")

        elif isinstance(payload, UserJourneyResult):
            lines.append("## 1. Vue d'Ensemble")
            lines.append(payload.overview)
            lines.append("")

            lines.append("## 2. Personas")
            for p in payload.personas:
                lines.append(f"### {p.name}")
                lines.append(p.profile)
                lines.append(self._format_sources(p.sources))
                lines.append("")

            lines.append("## 3. Étapes Chronologiques du Parcours")
            for s in payload.steps:
                lines.append(f"### Étape {s.step_number} : {s.stage} ({s.persona})")
                lines.append(f"- **Action** : {s.action}")
                lines.append(f"- **Objectif** : {s.user_goal}")
                lines.append(f"- **Point de contact** : {s.touchpoint}")
                lines.append(f"- **Points de friction** : {', '.join(s.pain_points)}")
                lines.append(f"- **Opportunités** : {', '.join(s.opportunities)}")
                lines.append(self._format_sources(s.sources))
                lines.append("")

            lines.append("## 4. Diagramme Mermaid")
            lines.append("```mermaid")
            lines.append(payload.mermaid_diagram)
            lines.append("```")

        elif isinstance(payload, RawNotesResult):
            lines.append("## 1. Bilan de Dé-duplication")
            lines.append(payload.deduplication_summary)
            lines.append("")

            lines.append("## 2. Piliers Thématiques Consolidés")
            for c in payload.clusters:
                lines.append(f"### {c.pillar} ({' '.join(c.tags)})")
                lines.append(c.summary)
                for idea in c.consolidated_ideas:
                    lines.append(
                        f"- **{idea.title}** ({idea.merged_count} occurrences fusionnées) : {idea.structured_content}{self._format_sources(idea.sources)}"
                    )
                lines.append("")

            lines.append("## 3. Prochaines Étapes Suggérées")
            for n in payload.suggested_next_steps:
                lines.append(
                    f"- **[{n.category} — Impact {n.impact}]** {n.action}{self._format_sources(n.sources)}"
                )

        return "\n".join(lines)

    def _markdown_to_docx(self, title: str, md_text: str) -> bytes:
        doc = DocxDocument()
        doc.add_heading(title, level=0)

        for raw_line in md_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("# "):
                continue
            if line.startswith("## "):
                doc.add_heading(line[3:], level=1)
            elif line.startswith("### "):
                doc.add_heading(line[4:], level=2)
            elif line.startswith("- "):
                doc.add_paragraph(line[2:].replace("**", ""), style="List Bullet")
            else:
                doc.add_paragraph(line.replace("**", ""))

        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    def _markdown_to_pdf(self, title: str, md_text: str) -> bytes:
        pdf = FPDF()
        pdf.set_margins(15, 15, 15)
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        usable_w = pdf.epw

        pdf.set_font("Helvetica", style="B", size=15)
        safe_title = title.encode("latin-1", errors="replace").decode("latin-1")
        pdf.multi_cell(usable_w, 9, safe_title, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
        pdf.ln(4)

        pdf.set_font("Helvetica", size=10)
        for raw_line in md_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("# "):
                continue
            clean = (
                line.replace("**", "")
                .replace("`", "")
                .replace("—", "-")
                .replace("–", "-")
                .replace("’", "'")
                .replace("‘", "'")
                .replace("«", '"')
                .replace("»", '"')
                .replace("•", "-")
                .encode("latin-1", errors="replace")
                .decode("latin-1")
            )
            pdf.set_x(pdf.l_margin)
            if clean.startswith("## "):
                pdf.ln(3)
                pdf.set_font("Helvetica", style="B", size=12)
                pdf.multi_cell(
                    usable_w, 7, clean[3:], new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR"
                )
                pdf.set_font("Helvetica", size=10)
            elif clean.startswith("### "):
                pdf.ln(2)
                pdf.set_font("Helvetica", style="B", size=11)
                pdf.multi_cell(
                    usable_w, 6, clean[4:], new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR"
                )
                pdf.set_font("Helvetica", size=10)
            else:
                pdf.multi_cell(
                    usable_w, 5.5, clean, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR"
                )

        return bytes(pdf.output())
