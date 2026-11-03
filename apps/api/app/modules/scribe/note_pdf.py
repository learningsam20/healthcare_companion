"""Formatted PDF export for signed clinical notes."""

from __future__ import annotations

import datetime as dt
import io
import uuid
from typing import Any

from app.modules.scribe.clinical_prose import display_sentence
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

TEAL = colors.HexColor("#0f766e")
INK = colors.HexColor("#10232e")
MUTED = colors.HexColor("#556a78")
RULE = colors.HexColor("#dbe4ea")
SURFACE = colors.HexColor("#f3f6f8")
SECTION_LABELS = (
    ("subjective", "S", "Subjective"),
    ("objective", "O", "Objective"),
    ("assessment", "A", "Assessment"),
    ("plan", "P", "Plan"),
)


class _LetterBadge(Flowable):
    """Small filled square with the SOAP letter."""

    def __init__(self, letter: str, size: float = 14) -> None:
        super().__init__()
        self.letter = letter
        self.size = size
        self.width = size
        self.height = size

    def draw(self) -> None:  # noqa: D102 — ReportLab API
        self.canv.setFillColor(TEAL)
        self.canv.roundRect(0, 0, self.size, self.size, 2, fill=1, stroke=0)
        self.canv.setFillColor(colors.white)
        self.canv.setFont("Helvetica-Bold", 8)
        self.canv.drawCentredString(self.size / 2, 3.5, self.letter)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "org": ParagraphStyle(
            "NoteOrg",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=TEAL,
            leading=14,
        ),
        "org_sub": ParagraphStyle(
            "NoteOrgSub",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=MUTED,
            leading=11,
        ),
        "title": ParagraphStyle(
            "NoteTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=INK,
            leading=20,
            spaceAfter=4,
        ),
        "meta": ParagraphStyle(
            "NoteMeta",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=MUTED,
            leading=12,
        ),
        "meta_strong": ParagraphStyle(
            "NoteMetaStrong",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=INK,
            leading=12,
        ),
        "section": ParagraphStyle(
            "NoteSection",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=INK,
            leading=14,
            spaceBefore=2,
        ),
        "body": ParagraphStyle(
            "NoteBody",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            textColor=INK,
            leading=14,
            leftIndent=4,
        ),
        "empty": ParagraphStyle(
            "NoteEmpty",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            textColor=MUTED,
            leading=12,
            leftIndent=4,
        ),
        "cell": ParagraphStyle(
            "NoteCell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            textColor=INK,
            leading=11,
        ),
        "cell_head": ParagraphStyle(
            "NoteCellHead",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=MUTED,
            leading=10,
        ),
        "sig_label": ParagraphStyle(
            "NoteSigLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=INK,
            leading=13,
            spaceBefore=4,
        ),
        "hash": ParagraphStyle(
            "NoteHash",
            parent=base["Normal"],
            fontName="Courier",
            fontSize=7.5,
            textColor=INK,
            leading=10,
            wordWrap="CJK",
        ),
        "footer": ParagraphStyle(
            "NoteFooter",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            textColor=MUTED,
            leading=9,
            alignment=TA_CENTER,
        ),
        "footer_left": ParagraphStyle(
            "NoteFooterLeft",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            textColor=MUTED,
            leading=9,
            alignment=TA_LEFT,
        ),
        "footer_right": ParagraphStyle(
            "NoteFooterRight",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            textColor=MUTED,
            leading=9,
            alignment=TA_RIGHT,
        ),
    }


def _esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _lines_for(content: dict[str, Any], field: str) -> list[str]:
    raw = content.get(field) or []
    out: list[str] = []
    for line in raw:
        if not isinstance(line, dict):
            continue
        text = display_sentence(str(line.get("text") or "")).strip()
        if text:
            out.append(text)
    return out


def _section_block(letter: str, title: str, lines: list[str], styles: dict[str, ParagraphStyle]) -> KeepTogether:
    head = Table(
        [[_LetterBadge(letter), Paragraph(_esc(title), styles["section"])]],
        colWidths=[18, None],
    )
    head.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    parts: list[Any] = [Spacer(1, 8), head, Spacer(1, 3)]
    if lines:
        for line in lines:
            parts.append(Paragraph(f"• {_esc(line)}", styles["body"]))
            parts.append(Spacer(1, 2))
    else:
        parts.append(Paragraph("Not recorded", styles["empty"]))
    return KeepTogether(parts)


def _medicine_table(medicines: list[dict[str, Any]], styles: dict[str, ParagraphStyle]) -> Any:
    if not medicines:
        return Paragraph("Not recorded", styles["empty"])
    header = [
        Paragraph("Medicine", styles["cell_head"]),
        Paragraph("Dose", styles["cell_head"]),
        Paragraph("Frequency", styles["cell_head"]),
        Paragraph("Duration", styles["cell_head"]),
        Paragraph("Instructions", styles["cell_head"]),
    ]
    rows: list[list[Any]] = [header]
    for item in medicines:
        rows.append(
            [
                Paragraph(_esc(str(item.get("name") or "—")), styles["cell"]),
                Paragraph(_esc(str(item.get("dose") or "—")), styles["cell"]),
                Paragraph(_esc(str(item.get("frequency") or "—")), styles["cell"]),
                Paragraph(_esc(str(item.get("duration") or "—")), styles["cell"]),
                Paragraph(_esc(str(item.get("instructions") or "—")), styles["cell"]),
            ]
        )
    table = Table(rows, colWidths=[95, 55, 70, 55, 145])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), SURFACE),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("GRID", (0, 0), (-1, -1), 0.4, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def render_clinical_note_pdf(
    *,
    note_id: uuid.UUID,
    title: str,
    patient_name: str,
    patient_id: uuid.UUID,
    version: int,
    language: str,
    status: str,
    signed_by: str,
    signed_at: dt.datetime | None,
    signed_hash: str,
    content: dict[str, Any],
    doctor_name: str | None = None,
    clinic_code: str | None = None,
    org_name: str = "Sahyog Care Companion",
) -> bytes:
    """Build a multi-page A4 PDF with repeating header/footer and SOAP layout."""
    styles = _styles()
    buffer = io.BytesIO()
    signed_label = (
        signed_at.astimezone(dt.UTC).strftime("%d %b %Y %H:%M UTC")
        if signed_at
        else "unsigned"
    )
    generated_at = dt.datetime.now(dt.UTC).strftime("%d %b %Y %H:%M UTC")
    note_id_short = str(note_id)
    patient_id_short = str(patient_id)[:8]

    def _header_footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        width, height = A4
        # Header band
        canvas.setStrokeColor(TEAL)
        canvas.setLineWidth(1.6)
        canvas.line(18 * mm, height - 14 * mm, width - 18 * mm, height - 14 * mm)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.setFillColor(TEAL)
        canvas.drawString(18 * mm, height - 11 * mm, org_name)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        right_meta = "Signed clinical record · Confidential"
        canvas.drawRightString(width - 18 * mm, height - 11 * mm, right_meta)
        # Footer
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.6)
        canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 9 * mm, f"Note {note_id_short}")
        canvas.drawCentredString(
            width / 2,
            9 * mm,
            f"Page {doc.page} · Generated {generated_at}",
        )
        canvas.drawRightString(
            width - 18 * mm,
            9 * mm,
            "For authorised care-team use only",
        )
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        title=title,
        author=org_name,
    )

    story: list[Any] = []
    story.append(Paragraph(_esc(title), styles["title"]))

    meta_rows = [
        [
            Paragraph("Patient", styles["meta_strong"]),
            Paragraph(_esc(f"{patient_name}  ·  {patient_id_short}"), styles["meta"]),
        ],
        [
            Paragraph("Clinician", styles["meta_strong"]),
            Paragraph(
                _esc(doctor_name or signed_by or "—")
                + (f"  ·  Clinic {_esc(clinic_code)}" if clinic_code else ""),
                styles["meta"],
            ),
        ],
        [
            Paragraph("Record", styles["meta_strong"]),
            Paragraph(
                _esc(
                    f"Version {version}  ·  {status.title()}  ·  {language}  ·  Signed {signed_label}"
                ),
                styles["meta"],
            ),
        ],
    ]
    meta = Table(meta_rows, colWidths=[55, 365])
    meta.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LINEBELOW", (0, -1), (-1, -1), 0.5, RULE),
            ]
        )
    )
    story.append(meta)
    story.append(Spacer(1, 6))

    for field, letter, label in SECTION_LABELS:
        story.append(_section_block(letter, label, _lines_for(content, field), styles))

    follow_up = content.get("follow_up") or {}
    follow_text = ""
    if isinstance(follow_up, dict):
        follow_text = display_sentence(str(follow_up.get("text") or "")).strip()
    story.append(Spacer(1, 10))
    story.append(Paragraph("Follow-up", styles["section"]))
    story.append(Spacer(1, 3))
    story.append(
        Paragraph(_esc(follow_text), styles["body"])
        if follow_text
        else Paragraph("Not recorded", styles["empty"])
    )

    story.append(Spacer(1, 10))
    story.append(Paragraph("Prescription", styles["section"]))
    story.append(Spacer(1, 4))
    medicines = content.get("medicines") or []
    story.append(
        _medicine_table(
            [item for item in medicines if isinstance(item, dict)],
            styles,
        )
    )

    story.append(Spacer(1, 16))
    story.append(Paragraph("Digital signature", styles["sig_label"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Signed by {_esc(signed_by or '—')}", styles["body"]))
    story.append(Paragraph(f"Signed at {_esc(signed_label)}", styles["body"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Content hash", styles["meta_strong"]))
    story.append(Paragraph(_esc(signed_hash or "—"), styles["hash"]))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "This hash covers the signed content. A correction creates a new version and a new hash.",
            styles["meta"],
        )
    )

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buffer.getvalue()
