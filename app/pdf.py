"""80 mm till-roll style PDF receipts (fpdf2). Core fonts are latin-1, so text is squeezed into it."""

import qrcode
from fpdf import FPDF

from .split import kwacha

W = 80  # mm, thermal roll width


def _t(s) -> str:
    return str(s).replace("—", "-").replace("…", "...").encode("latin-1", "replace").decode("latin-1")


def bill_pdf(title: str, subtitle_lines: list[str], items: list[tuple[int, str, int]], totals: list[tuple[str, int]],
             footer_lines: list[str] = (), qr: str | None = None) -> bytes:
    """items: (qty, name, line_total_minor); totals: (label, minor), the last one printed bold."""
    height = 45 + 5 * (len(items) + len(totals) + len(subtitle_lines) + len(footer_lines)) + (40 if qr else 0)
    pdf = FPDF(unit="mm", format=(W, height))
    pdf.set_margins(5, 5, 5)
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 7, _t(title), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    for line in subtitle_lines:
        pdf.cell(0, 4, _t(line), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    dashes = lambda: (pdf.set_font("Courier", "", 8), pdf.cell(0, 4, "-" * 44, align="C", new_x="LMARGIN", new_y="NEXT"))
    dashes()
    pdf.set_font("Helvetica", "", 9)
    for qty, name, line in items:
        pdf.cell(8, 5, f"{qty}x")
        pdf.cell(40, 5, _t(name)[:28])
        pdf.cell(0, 5, kwacha(line), align="R", new_x="LMARGIN", new_y="NEXT")
    dashes()
    for i, (label, minor) in enumerate(totals):
        last = i == len(totals) - 1
        pdf.set_font("Helvetica", "B" if last else "", 11 if last else 9)
        pdf.cell(48, 6 if last else 5, _t(label))
        pdf.cell(0, 6 if last else 5, kwacha(minor), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 8)
    for line in footer_lines:
        pdf.cell(0, 4, _t(line), align="C", new_x="LMARGIN", new_y="NEXT")
    if qr:
        pdf.ln(2)
        pdf.image(qrcode.make(qr, border=1).get_image(), x=(W - 30) / 2, w=30)
    return bytes(pdf.output())


def receipt_pdf(r, items, pays, names, url: str) -> bytes:
    totals = [("Subtotal", r.subtotal_minor)]
    totals += [(label, v) for label, v in (("Tax", r.tax_minor), ("Service", r.service_minor), ("Tip", r.tip_minor)) if v]
    totals.append(("TOTAL", r.total_minor))
    footer = [f"{names.get(p.participant_id, 'Customer')}: {kwacha(p.amount_minor)} / ${p.amount_usdc} USDC - {p.status}"
              for p in pays]
    footer += ["", "Payments by DevDraft - TrackSplit"]
    return bill_pdf(r.merchant or "Receipt", [f"Receipt #{r.id}", r.created_at.strftime("%d %b %Y %H:%M UTC")],
                    [(i.qty, i.name, i.line_total_minor) for i in items], totals, footer, qr=url)
