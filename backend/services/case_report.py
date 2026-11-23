"""Case report (PDF) for court and prosecution: what happened, who did what and when, and every
piece of evidence with its SHA-256 and custody-chain check.

The PDF goes into the evidence package (listed in MANIFEST.sha256, so it is covered by the
package signature) and can be downloaded on its own. Text in Bangla needs a font with Bengali
glyphs: set CASE_REPORT_FONT to a .ttf (e.g. NotoSansBengali-Regular.ttf); without it such text
is replaced and the report says where the original is (incident.json in the package).
"""

from __future__ import annotations

import io
import os
from datetime import datetime
from typing import List, Optional

_FONT = None


def _font() -> str:
    global _FONT
    if _FONT:
        return _FONT
    path = os.getenv("CASE_REPORT_FONT", "")
    if path and os.path.isfile(path):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        pdfmetrics.registerFont(TTFont("CaseFont", path))
        _FONT = "CaseFont"
    else:
        _FONT = "Helvetica"
    return _FONT


_TYPO = str.maketrans({"—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...", "→": "->",
                       "·": "-", "≈": "~", "\u00a0": " "})


def _t(v) -> str:
    """Text safe for the font in use; XML-escaped for Paragraph."""
    from xml.sax.saxutils import escape
    s = "" if v is None else str(v)
    if _font() == "Helvetica":
        s = s.translate(_TYPO)
        enc = s.encode("latin-1", "replace").decode("latin-1")
        if enc != s:
            s = enc.replace("?", "·") + " [non-Latin text: see incident.json]"
    return escape(s)


def _when(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S") + (" UTC" if dt.tzinfo is None or dt.utcoffset().total_seconds() == 0 else "")


def _dur(sec: Optional[float]) -> str:
    if sec is None:
        return "not reached"
    sec = int(sec)
    return f"{sec // 3600} h {sec % 3600 // 60} min" if sec >= 3600 else f"{sec // 60} min {sec % 60} s"


def build_pdf(case: dict) -> bytes:
    """`case`: see evidence_package.build_package (incident, alert, events, notes, messages,
    officers, stages, stills, items, actor, made)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font = _font()
    ss = getSampleStyleSheet()
    base = ParagraphStyle("b", parent=ss["Normal"], fontName=font, fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=base, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#444444"))
    h1 = ParagraphStyle("h1", parent=base, fontSize=16, leading=20, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=base, fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=4)
    inc = case["incident"]

    def table(rows: List[list], widths, header=True):
        data = [[Paragraph(c if isinstance(c, str) else _t(c), small if header and i == 0 else base) for c in r]
                for i, r in enumerate(rows)]
        tb = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        style = [("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#bbbbbb")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")))
        tb.setStyle(TableStyle(style))
        return tb

    W = A4[0] - 30 * mm
    story = [
        Paragraph(_t(f"Case report {inc.ticket_id}"), h1),
        Paragraph(_t(inc.title), base),
        Paragraph(_t(f"Generated {_when(case['made'])} by {case['actor']}. This report is part of the evidence package "
                     f"and is listed in its MANIFEST.sha256; the package signature covers it."), small),
        Spacer(1, 6),
        Paragraph("Summary", h2),
        table([[ "Field", "Value"],
               ["Ticket", _t(inc.ticket_id)], ["Type", _t(inc.incident_type)], ["Priority", _t(inc.priority)],
               ["Status", _t(inc.status)], ["Opened", _t(_when(inc.created_at))], ["Resolved", _t(_when(inc.resolved_at))],
               ["Camera", _t(f"{inc.camera_location or '—'} ({inc.camera_id or '—'})")],
               ["Position", _t(f"{inc.lat:.5f}, {inc.lng:.5f}" if inc.lat is not None and inc.lng is not None else "—")],
               ["Area", _t(case.get("area") or "Not recorded")], ["Case owner", _t(inc.assigned_name or "—")],
               ["Person / plate", _t(" / ".join(x for x in (inc.person_name, inc.plate_number) if x) or "—")],
               ["Description", _t(inc.description or "—")]],
              [35 * mm, W - 35 * mm]),
    ]
    alert = case.get("alert")
    if alert:
        story += [Paragraph("Originating alert", h2),
                  table([["Field", "Value"], ["Alert", _t(f"#{alert.id} {alert.alert_type} ({alert.severity})")],
                         ["Time", _t(_when(alert.timestamp))], ["Message", _t(alert.message or "—")],
                         ["Operator review", _t(f"{alert.review_status or 'pending'}" + (f": {alert.review_note}" if alert.review_note else ""))]],
                        [35 * mm, W - 35 * mm]),
                  Paragraph("Identification alerts are possible matches that an operator verified; they are not proof "
                            "of identity on their own.", small)]
    stages = case.get("stages") or {}
    story += [Paragraph("Response", h2),
              table([["Officer assigned", "Officer answered", "Officer on scene", "Resolved"],
                     [_t(_dur(stages.get("dispatch"))), _t(_dur(stages.get("acknowledge"))),
                      _t(_dur(stages.get("arrive"))), _t(_dur(stages.get("resolve")))]],
                    [W / 4] * 4)]
    if case.get("officers"):
        story += [Spacer(1, 4), table([["Officer", "Rank / badge", "State", "Assigned", "Note"]] + [
            [_t(o["name"]), _t(" / ".join(x for x in (o.get("rank"), o.get("badge_no")) if x) or "—"), _t(o["state"]),
             _t(_when(o["assigned_at"])), _t("Assigned from a neighbouring area" if o.get("out_of_area") else "")]
            for o in case["officers"]], [45 * mm, 32 * mm, 25 * mm, 35 * mm, W - 137 * mm])]

    items = case.get("items") or []
    stills = case.get("stills") or []
    story.append(Paragraph(f"Evidence ({len(items) + len(stills)})", h2))
    if items:
        story.append(table([["Ref", "What", "Added", "SHA-256 of the original", "Custody chain"]] + [
            [_t(i["ref"]), _t(f"{i['kind']}: {i.get('filename') or ''} {('— ' + i['description']) if i.get('description') else ''}"),
             _t(f"{_when(i['uploaded_at'])} by {i.get('by') or 'system'}"), f"<font size=6.5>{i['sha256']}</font>",
             _t(f"{'intact' if i['chain_ok'] else 'BROKEN'}, {i['records']} records")]
            for i in items], [24 * mm, 45 * mm, 33 * mm, 52 * mm, W - 154 * mm]))
        thumbs = [i for i in items if i.get("thumb")][:6]
        if thumbs:
            cells = []
            for i in thumbs:
                img = Image(io.BytesIO(i["thumb"]))
                ratio = img.imageHeight / float(img.imageWidth or 1)
                img.drawWidth, img.drawHeight = 55 * mm, min(55 * mm * ratio, 45 * mm)
                cells.append([img, Paragraph(_t(i["ref"]), small)])
            rows = [cells[k:k + 3] for k in range(0, len(cells), 3)]
            grid = Table([[Table([[c[0]], [c[1]]]) for c in r] + [""] * (3 - len(r)) for r in rows], colWidths=[W / 3] * 3)
            story += [Spacer(1, 4), KeepTogether(grid),
                      Paragraph("Thumbnails are for identification only; the original files are in the package.", small)]
    if stills:
        story.append(Spacer(1, 4))
        story.append(table([["Still", "Time", "Camera", "Stored SHA-256", "Custody records"]] + [
            [_t(s["id"]), _t(_when(s["time"])), _t(s.get("camera") or "—"), f"<font size=6.5>{s.get('sha256') or '—'}</font>",
             _t(s["records"])] for s in stills], [18 * mm, 35 * mm, 40 * mm, 60 * mm, W - 153 * mm]))
    if not items and not stills:
        story.append(Paragraph("No evidence files.", base))

    if case.get("messages"):
        story += [Paragraph("Messages between dispatch and officers", h2),
                  table([["Time", "From", "Message"]] + [
                      [_t(_when(m.created_at)), _t(f"{m.author_name} ({'field' if m.author_role == 'police' else 'dispatch'})"),
                       _t((m.body or "") + (f" [photo {m.evidence_ref}]" if m.evidence_ref else ""))]
                      for m in case["messages"]], [35 * mm, 45 * mm, W - 80 * mm])]
    if case.get("notes"):
        story += [Paragraph("Case notes", h2),
                  table([["Time", "By", "Note"]] + [[_t(_when(n.created_at)), _t(n.author_name), _t(n.body)]
                                                   for n in case["notes"]], [35 * mm, 30 * mm, W - 65 * mm])]
    story += [Paragraph("Timeline", h2),
              table([["Time", "Event", "By", "Details"]] + [
                  [_t(_when(e.created_at)), _t(e.event_type), _t(e.actor or "SYSTEM"), _t(e.message)]
                  for e in case["events"]], [33 * mm, 26 * mm, 26 * mm, W - 85 * mm]),
              Spacer(1, 10),
              Paragraph("How to check this package: run <font name='Courier'>sha256sum -c MANIFEST.sha256</font> in the "
                        "unzipped folder (every line must say OK), and upload the ZIP to the system's package check to confirm "
                        "SIGNATURE.txt. Custody chains are hash-linked: a changed or removed record breaks the chain.", small)]

    buf = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(15 * mm, 10 * mm, f"Aegis case report {inc.ticket_id}")
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=16 * mm,
                      title=f"Case report {inc.ticket_id}", author="Aegis").build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
