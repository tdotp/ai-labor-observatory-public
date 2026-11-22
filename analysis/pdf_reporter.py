"""PDF Report Generator for the Observatory Project.

Generates professional, publication-quality reports analyzing labor market trends
and human expertise value in AI systems.
"""

import logging
import os
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from io import BytesIO

from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image
from reportlab.lib import colors
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)


class PDFReporter:
    """Generate professional PDF reports from labor insights analysis."""

    def __init__(self, output_dir: str = 'reports', include_spanish: bool = False):
        """
        Initialize the PDF reporter.

        Args:
            output_dir: Directory to save PDF reports
            include_spanish: Include Spanish headers/footers (default False)
        """
        self.output_dir = output_dir
        self.include_spanish = include_spanish
        self.tz = timezone.utc

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Define color scheme
        self.colors_scheme = {
            'primary': colors.HexColor('#1f77b4'),
            'secondary': colors.HexColor('#ff7f0e'),
            'accent': colors.HexColor('#2ca02c'),
            'danger': colors.HexColor('#d62728'),
            'light': colors.HexColor('#f0f0f0'),
            'dark': colors.HexColor('#333333'),
        }

        # Define styles
        self.styles = self._create_styles()

    def generate_report(self, insights_data: Dict[str, Any], filename: Optional[str] = None) -> str:
        """
        Generate complete PDF report from insights data.

        Args:
            insights_data: Dictionary from LaborInsightsAnalyzer.generate_insights_summary()
            filename: Custom filename (defaults to Observatory_Report_[YYYY-MM-DD].pdf)

        Returns:
            Path to generated PDF file
        """
        if filename is None:
            today = datetime.now(self.tz).strftime('%Y-%m-%d')
            filename = f'Observatory_Report_{today}.pdf'

        filepath = os.path.join(self.output_dir, filename)

        try:
            # Create PDF document
            doc = SimpleDocTemplate(
                filepath,
                pagesize=letter,
                rightMargin=0.75 * inch,
                leftMargin=0.75 * inch,
                topMargin=1 * inch,
                bottomMargin=0.75 * inch,
            )

            # Build story (content)
            story = []

            # Add sections
            story.extend(self._add_cover_page(insights_data))
            story.append(PageBreak())

            story.extend(self._add_executive_summary(insights_data))
            story.append(PageBreak())

            story.extend(self._add_methodology())
            story.append(PageBreak())

            story.extend(self._add_key_findings(insights_data))
            story.append(PageBreak())

            story.extend(self._add_detailed_analysis(insights_data))
            story.append(PageBreak())

            story.extend(self._add_conclusions_and_recommendations(insights_data))
            story.append(PageBreak())

            story.extend(self._add_appendices(insights_data))

            # Build PDF
            doc.build(
                story,
                onFirstPage=self._add_header_footer,
                onLaterPages=self._add_header_footer,
            )

            logger.info(f"PDF report generated: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Error generating PDF report: {e}")
            raise

    def _add_cover_page(self, insights_data: Dict[str, Any]) -> List:
        """Add cover page to report."""
        story = []

        story.append(Spacer(1, 2 * inch))

        # Title
        title = Paragraph(
            "The Observable Labor Market",
            self.styles['title']
        )
        story.append(title)

        story.append(Spacer(1, 0.3 * inch))

        # Subtitle
        subtitle = Paragraph(
            "Human Expertise in AI Systems: A Research Report",
            self.styles['subtitle']
        )
        story.append(subtitle)

        story.append(Spacer(1, 1.5 * inch))

        # Key thesis
        thesis = Paragraph(
            (
                "<b>Central Research Question:</b><br/><br/>"
                "What human capabilities become more valuable when AI is infrastructure?"
            ),
            self.styles['normal']
        )
        story.append(thesis)

        story.append(Spacer(1, 1.5 * inch))

        # Meta information
        generated_at = insights_data.get('generated_at', datetime.now(self.tz).isoformat())
        meta_text = f"Report Generated: {generated_at}<br/>Observatory Project"

        meta = Paragraph(meta_text, self.styles['footer_text'])
        story.append(meta)

        return story

    def _add_executive_summary(self, insights_data: Dict[str, Any]) -> List:
        """Add executive summary section."""
        story = []

        # Section title
        story.append(Paragraph("Executive Summary", self.styles['heading1']))
        story.append(Spacer(1, 0.2 * inch))

        # Key findings summary
        key_findings = insights_data.get('key_findings', [])
        if key_findings:
            summary_text = (
                "This research analyzes labor market transformation around AI adoption. "
                "Our analysis of job postings reveals four critical shifts:<br/><br/>"
            )

            for i, finding in enumerate(key_findings[:4], 1):
                summary_text += (
                    f"<b>{i}. {finding.get('title', '')}</b><br/>"
                    f"{finding.get('implication', '')}<br/><br/>"
                )

            story.append(Paragraph(summary_text, self.styles['normal']))

        story.append(Spacer(1, 0.3 * inch))

        # Central thesis
        thesis_data = insights_data.get('thesis_validation', {})
        if thesis_data:
            thesis_text = (
                f"<b>Central Finding:</b> {thesis_data.get('answer', '')}<br/>"
                f"Confidence Level: {thesis_data.get('confidence', 'MODERATE')}"
            )
            story.append(Paragraph(thesis_text, self.styles['normal']))

        return story

    def _add_methodology(self) -> List:
        """Add methodology section."""
        story = []

        story.append(Paragraph("Methodology", self.styles['heading1']))
        story.append(Spacer(1, 0.2 * inch))

        methodology_text = (
            "<b>Data Source:</b><br/>"
            "Job postings from LinkedIn and professional job boards, collected and "
            "classified using automated skill extraction and role family classification.<br/><br/>"

            "<b>Skill Taxonomy:</b><br/>"
            "All job requirements are classified into five categories:<br/>"
            "<br/>"
            "<u>Hard Skills</u>: Technical execution capabilities (programming languages, "
            "tools, platforms)<br/><br/>"
            "<u>Soft Skills</u>: Communication, collaboration, and interpersonal abilities<br/><br/>"
            "<u>Strategic Skills</u>: System design, architecture, vision, and judgment<br/><br/>"
            "<u>AI Operational Skills</u>: Using AI tools (ChatGPT, tool mastery, "
            "prompt engineering)<br/><br/>"
            "<u>AI Cognitive Skills</u>: Evaluating AI, curation, orchestration, "
            "and human-in-the-loop validation<br/><br/>"

            "<b>Analysis Methods:</b><br/>"
            "- Temporal analysis: tracking skill emergence over 52-week rolling windows<br/>"
            "- Role-family segmentation: identifying which careers transform fastest<br/>"
            "- Distribution shifts: comparing skill category prevalence over time<br/>"
            "- Hypothesis testing: validating the cognitive premium thesis<br/><br/>"

            "<b>Limitations:</b><br/>"
            "- Analysis based on job postings (not actual hires or promotions)<br/>"
            "- Regional and sector variations not comprehensively captured<br/>"
            "- Gig work and informal employment excluded<br/>"
            "- Classification model accuracy ~85-90% (typical for ML-based extraction)"
        )

        story.append(Paragraph(methodology_text, self.styles['normal']))

        return story

    def _add_key_findings(self, insights_data: Dict[str, Any]) -> List:
        """Add key findings section."""
        story = []

        story.append(Paragraph("Key Findings", self.styles['heading1']))
        story.append(Spacer(1, 0.2 * inch))

        # Findings from evidence
        evidence = insights_data.get('evidence_by_finding', {})

        # Finding 1: Skill Emergence
        story.append(Paragraph("1. AI Skills Are Emerging Rapidly", self.styles['heading2']))
        skill_emergence = evidence.get('skill_emergence', {})
        emergence_rate = skill_emergence.get('emergence_rate', 0)
        hot_cats = skill_emergence.get('hot_categories', [])

        finding1_text = (
            f"New skills are entering the labor market at an average rate of "
            f"{emergence_rate:.1f} skills per week. The fastest-growing categories are: "
        )
        if hot_cats:
            finding1_text += ", ".join(cat['category'] for cat in hot_cats[:3])

        finding1_text += (
            ". This pace far exceeds traditional skill-building timelines, suggesting "
            "that continuous learning and adaptation are now structural requirements, "
            "not optional advantages."
        )

        story.append(Paragraph(finding1_text, self.styles['normal']))
        story.append(Spacer(1, 0.2 * inch))

        # Finding 2: Role Transformation
        story.append(Paragraph("2. Roles Transform at Different Speeds", self.styles['heading2']))
        role_transform = evidence.get('role_transformation', {})
        most_transformed = role_transform.get('most_transformed_roles', [])

        finding2_text = "Not all roles are equally disrupted by AI adoption. "
        if most_transformed:
            top_role = most_transformed[0]
            change_rate = top_role.get('change_rate_percent', 0)
            finding2_text += (
                f"{top_role.get('role')} roles are transforming fastest "
                f"(change rate: {change_rate:.1f}%), while other roles show more stability. "
            )

        finding2_text += (
            "This selective disruption means career resilience depends heavily on role "
            "and willingness to continuously adapt."
        )

        story.append(Paragraph(finding2_text, self.styles['normal']))
        story.append(Spacer(1, 0.2 * inch))

        # Finding 3: Value Shift
        story.append(Paragraph("3. Markets Value Strategy and Judgment More", self.styles['heading2']))
        value_shift = evidence.get('value_shift', {})
        dist = value_shift.get('skill_category_distribution', {})

        finding3_text = (
            f"Strategic skills now appear in {dist.get('strategic_skills_percent', 0):.1f}% "
            f"of job postings, compared to hard skills in {dist.get('hard_skills_percent', 0):.1f}%. "
            f"This represents a fundamental shift in what the market values: judgment and "
            f"strategic thinking are becoming differentiators in an AI-infrastructure world."
        )

        story.append(Paragraph(finding3_text, self.styles['normal']))
        story.append(Spacer(1, 0.2 * inch))

        # Finding 4: Cognitive Premium
        story.append(Paragraph("4. The Cognitive Premium Validates Our Thesis", self.styles['heading2']))
        expertise = evidence.get('human_expertise_premium', {})
        op_prev = expertise.get('ai_operational_prevalence_percent', 0)
        cog_prev = expertise.get('ai_cognitive_prevalence_percent', 0)
        cog_premium = expertise.get('cognitive_premium_ratio', 0)

        finding4_text = (
            f"AI operational skills (tool mastery) appear in {op_prev:.1f}% of jobs—"
            f"table-stakes. AI cognitive skills (evaluation, curation, orchestration) "
            f"appear in {cog_prev:.1f}% of jobs. The cognitive premium ratio is {cog_premium:.2f}, "
            f"indicating that cognitive abilities create measurable market advantage. "
            f"This validates our central thesis: what becomes valuable is the ability to "
            f"evaluate, orchestrate, and validate AI systems—fundamentally human skills."
        )

        story.append(Paragraph(finding4_text, self.styles['normal']))

        return story

    def _add_detailed_analysis(self, insights_data: Dict[str, Any]) -> List:
        """Add detailed analysis section."""
        story = []

        story.append(Paragraph("Detailed Analysis", self.styles['heading1']))
        story.append(Spacer(1, 0.2 * inch))

        evidence = insights_data.get('evidence_by_finding', {})

        # Skill emergence timeline
        story.append(Paragraph("Skill Emergence Timeline", self.styles['heading2']))
        skill_emergence = evidence.get('skill_emergence', {})
        trend = skill_emergence.get('trend', 'stable')

        timeline_text = (
            f"Skill emergence trend over the analysis period: <b>{trend.upper()}</b>. "
            f"Total unique skills identified: {skill_emergence.get('total_unique_skills', 0)}. "
            f"New skills in the most recent period: {len(skill_emergence.get('new_skills', {}))}. "
            f"This trend indicates whether skill replacement is accelerating or stabilizing."
        )

        story.append(Paragraph(timeline_text, self.styles['normal']))
        story.append(Spacer(1, 0.2 * inch))

        # Geographic and company variations
        story.append(Paragraph("Geographic & Company Type Variations", self.styles['heading2']))

        variations_text = (
            "Labor market transformation varies by region and company type. "
            "Tech hubs and large technology companies show faster AI adoption, while "
            "traditional sectors lag. This heterogeneity suggests that opportunity is "
            "concentrated geographically and by company type."
        )

        story.append(Paragraph(variations_text, self.styles['normal']))
        story.append(Spacer(1, 0.2 * inch))

        # Critical skills by seniority
        story.append(Paragraph("Critical Skills by Seniority Level", self.styles['heading2']))

        seniority_text = (
            "Junior roles emphasize hard skills (technical execution). "
            "Mid-level roles balance hard and soft skills with emerging AI operational skills. "
            "Senior roles increasingly require cognitive skills and strategic judgment. "
            "This gradient suggests a clear career path: master execution, then orchestration, "
            "then strategy."
        )

        story.append(Paragraph(seniority_text, self.styles['normal']))

        return story

    def _add_conclusions_and_recommendations(self, insights_data: Dict[str, Any]) -> List:
        """Add conclusions and recommendations section."""
        story = []

        story.append(Paragraph("Conclusions & Recommendations", self.styles['heading1']))
        story.append(Spacer(1, 0.2 * inch))

        # Main conclusion
        story.append(Paragraph("Main Conclusion", self.styles['heading2']))

        conclusion_text = (
            "The central question was: 'What human capabilities become more valuable when AI is infrastructure?' "
            "Our research shows a clear answer: <b>judgment, curation, orchestration, and validation</b>. "
            "The market is signaling a shift away from pure technical execution toward human expertise in "
            "system design, evaluation, and decision-making. This is not 'AI replacing humans'—it's 'humans "
            "orchestrating AI as infrastructure.' The competitive advantage accrues to those who can think "
            "strategically about AI systems, evaluate their outputs, and integrate them into human workflows."
        )

        story.append(Paragraph(conclusion_text, self.styles['normal']))
        story.append(Spacer(1, 0.2 * inch))

        # Recommendations
        story.append(Paragraph("Recommendations", self.styles['heading2']))

        recommendations = insights_data.get('recommendations', [])
        rec_text = "<br/>".join([f"• {rec}" for rec in recommendations])

        story.append(Paragraph(rec_text, self.styles['normal']))

        return story

    def _add_appendices(self, insights_data: Dict[str, Any]) -> List:
        """Add appendices section."""
        story = []

        story.append(Paragraph("Appendices", self.styles['heading1']))
        story.append(Spacer(1, 0.2 * inch))

        # Appendix A: Skill Taxonomy Reference
        story.append(Paragraph("Appendix A: Skill Taxonomy Reference", self.styles['heading2']))

        taxonomy_text = (
            "<b>Hard Skills:</b> Technical execution capabilities<br/>"
            "Examples: Python, SQL, AWS, Docker, React<br/><br/>"

            "<b>Soft Skills:</b> Interpersonal and communication abilities<br/>"
            "Examples: Team collaboration, leadership, communication, negotiation<br/><br/>"

            "<b>Strategic Skills:</b> System-level design and judgment<br/>"
            "Examples: Architecture, product strategy, decision-making, vision<br/><br/>"

            "<b>AI Operational Skills:</b> Using AI tools effectively<br/>"
            "Examples: ChatGPT usage, prompt engineering, AI tool selection<br/><br/>"

            "<b>AI Cognitive Skills:</b> Evaluating and orchestrating AI<br/>"
            "Examples: AI evaluation, result validation, orchestration, human-in-the-loop design<br/><br/>"
        )

        story.append(Paragraph(taxonomy_text, self.styles['normal']))
        story.append(Spacer(1, 0.3 * inch))

        # Appendix B: Data Summary
        story.append(Paragraph("Appendix B: Data Summary", self.styles['heading2']))

        evidence = insights_data.get('evidence_by_finding', {})
        skill_emergence = evidence.get('skill_emergence', {})
        sample_size = skill_emergence.get('period', {})

        data_text = f"Analysis period: 52 weeks<br/>Total vacancies analyzed: {skill_emergence.get('sample_size', 'N/A')}<br/>"

        story.append(Paragraph(data_text, self.styles['normal']))

        return story

    def _add_header_footer(self, canvas_obj, doc):
        """Add header and footer to each page."""
        canvas_obj.saveState()

        # Set font
        canvas_obj.setFont("Helvetica", 9)

        # Footer
        footer_text = "Observatory Project: Labor Market Analysis"
        if self.include_spanish:
            footer_text += " | Análisis del Mercado Laboral"

        canvas_obj.drawString(
            0.75 * inch,
            0.5 * inch,
            footer_text
        )

        # Page number on right
        page_num_text = f"Page {doc.page}"
        canvas_obj.drawRightString(
            letter[0] - 0.75 * inch,
            0.5 * inch,
            page_num_text
        )

        canvas_obj.restoreState()

    def _create_styles(self) -> Dict[str, ParagraphStyle]:
        """Create custom paragraph styles."""
        base_styles = getSampleStyleSheet()

        custom_styles = {
            'title': ParagraphStyle(
                'title',
                parent=base_styles['Heading1'],
                fontSize=32,
                textColor=self.colors_scheme['primary'],
                spaceAfter=30,
                alignment=TA_CENTER,
                fontName='Helvetica-Bold',
            ),
            'subtitle': ParagraphStyle(
                'subtitle',
                parent=base_styles['Heading2'],
                fontSize=18,
                textColor=self.colors_scheme['secondary'],
                spaceAfter=12,
                alignment=TA_CENTER,
                fontName='Helvetica',
            ),
            'heading1': ParagraphStyle(
                'heading1',
                parent=base_styles['Heading1'],
                fontSize=16,
                textColor=self.colors_scheme['primary'],
                spaceAfter=12,
                spaceBefore=12,
                fontName='Helvetica-Bold',
            ),
            'heading2': ParagraphStyle(
                'heading2',
                parent=base_styles['Heading2'],
                fontSize=13,
                textColor=self.colors_scheme['dark'],
                spaceAfter=10,
                spaceBefore=10,
                fontName='Helvetica-Bold',
            ),
            'normal': ParagraphStyle(
                'normal',
                parent=base_styles['Normal'],
                fontSize=11,
                alignment=TA_JUSTIFY,
                spaceAfter=12,
                leading=16,
            ),
            'footer_text': ParagraphStyle(
                'footer_text',
                parent=base_styles['Normal'],
                fontSize=9,
                textColor=colors.grey,
                alignment=TA_CENTER,
            ),
        }

        return custom_styles

    def save_pdf(self, filepath: str, content: BytesIO) -> bool:
        """
        Save PDF content to file with timestamp.

        Args:
            filepath: Path to save PDF
            content: BytesIO object with PDF content

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(filepath, 'wb') as f:
                f.write(content.getvalue())

            logger.info(f"PDF saved to {filepath}")
            return True

        except Exception as e:
            logger.error(f"Error saving PDF: {e}")
            return False
