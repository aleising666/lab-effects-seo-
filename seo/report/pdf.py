"""Render the report data as a readable PDF (reportlab, no external services).

Layout:
  Page 1   Title, date, summary tiles (pages crawled, open findings by severity,
           new / fixed), then "Fix first": every high and medium finding with a
           plain-English note on what to do.
  Next     "Lower priority", grouped by check with counts and example pages.
  Then     Search Console: clicks/impressions, close-to-page-one queries,
           position drops, new queries.
  Then     Rankings (movers, new/lost page one), Competitor keyword gaps,
           Backlinks (totals, new/lost referring domains). Each says "no data
           yet" until its pull has run.
"""
import os
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .build import path_of

# Brand colors (from the theme's brand standard)
TEAL, GOLD, LEAF = colors.HexColor("#108090"), colors.HexColor("#DAA423"), colors.HexColor("#60B050")
INK, CREAM, GRAY = colors.HexColor("#072326"), colors.HexColor("#EDEEE2"), colors.HexColor("#6B7280")
SEV_COLOR = {"high": colors.HexColor("#C0392B"), "medium": GOLD, "low": GRAY}
MOVE_LABEL = "(3+ places)"

# What to do about each check, in plain English, for the "Fix first" list.
ADVICE = {
    "broken-link": "Fix or remove the link. If the target moved, point at the new URL.",
    "not-found": "The sitemap lists a page that 404s. Remove it from the sitemap or restore the page.",
    "server-error": "The page returned a server error. Reload to confirm, then check the theme or app that renders it.",
    "fetch-error": "The crawler could not load this page. Check that it loads in a browser.",
    "redirect-chain": "Point the link straight at the final URL so visitors and Google skip the hops.",
    "redirect-link": "Update the link to the final URL. Usually an old Webflow or pre-rename URL.",
    "old-domain-link": "Change the link to labeffects.com. The old shop domain redirects, but it should not be linked.",
    "title-double-brand": "Remove 'Lab Effects' from the SEO title; the theme appends ' – Lab Effects Shop' automatically.",
    "title-missing": "Add an SEO title in the page's Search engine listing.",
    "title-typo": "Fix the spelling in the SEO title.",
    "meta-missing": "Write a meta description (about 150 characters) in the Search engine listing.",
    "thin-content": "Add visible copy that explains what the page is for. Two or three sentences under the heading is enough.",
    "few-internal-links": "Add 2 or 3 links in the body to collections, products or related posts.",
    "placeholder-text": "Leftover bracketed text is printing on the page. Replace it with real copy or delete it.",
    "faq-schema-mismatch": "The FAQ schema and the visible FAQ differ. Regenerate the schema so both lists match word for word.",
    "faq-schema-on-product": "Remove FAQPage schema from product pages; it belongs on the collection page only.",
    "canonical-mismatch": "The canonical tag points at a different URL. Usually a renamed handle; confirm which URL should win.",
    "noindex": "The page is hidden from Google. Confirm that is intended.",
    "h1-missing": "Give the page one H1 heading.",
    "stale-count": "Copy carries an old strain count. The catalog lists 130+.",
}


def _font():
    for cand in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial Unicode.ttf"]:
        if os.path.exists(cand):
            bold = cand.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
            try:
                pdfmetrics.registerFont(TTFont("Body", cand))
                pdfmetrics.registerFont(TTFont("BodyBold", bold if os.path.exists(bold) else cand))
                return "Body", "BodyBold"
            except Exception:
                pass
    return "Helvetica", "Helvetica-Bold"


def _esc(s: str) -> str:
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"[→]", "to", s)  # arrows are not in every font


def render(d: dict, out_path: str) -> str:
    body_font, bold_font = _font()
    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("h1", parent=ss["Title"], fontName=bold_font, fontSize=20, textColor=INK, alignment=TA_LEFT, spaceAfter=2)
    H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName=bold_font, fontSize=13, textColor=TEAL, spaceBefore=14, spaceAfter=6)
    P = ParagraphStyle("p", parent=ss["BodyText"], fontName=body_font, fontSize=9.5, leading=13, textColor=INK)
    SMALL = ParagraphStyle("small", parent=P, fontSize=8.5, leading=11, textColor=GRAY)
    MONO = ParagraphStyle("mono", parent=P, fontSize=8.5, leading=11, textColor=TEAL)

    story = []
    story.append(Paragraph("Lab Effects SEO report", H1))
    story.append(Paragraph(f"{d['date']} · {d['site']}", SMALL))
    story.append(Spacer(1, 10))

    c = d["crawl"]
    if not c:
        story.append(Paragraph("No crawl has run yet.", P))
    else:
        o = c["open"]
        tiles = [["Pages crawled", "Open findings", "High", "Medium", "Low",
                  "New since last run" if not c["first_run"] else "First run", "Fixed since last run"],
                 [str(c["pages"]), str(sum(o.values())), str(o["high"]), str(o["medium"]), str(o["low"]),
                  str(c["new"]) if c["new"] is not None else "–", str(c["fixed"]) if c["fixed"] is not None else "–"]]
        t = Table(tiles, colWidths=[1.0 * inch] * 7)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), CREAM), ("TEXTCOLOR", (0, 0), (-1, 0), GRAY),
            ("FONTNAME", (0, 0), (-1, 0), body_font), ("FONTSIZE", (0, 0), (-1, 0), 7.5),
            ("FONTNAME", (0, 1), (-1, 1), bold_font), ("FONTSIZE", (0, 1), (-1, 1), 16),
            ("TEXTCOLOR", (2, 1), (2, 1), SEV_COLOR["high"]), ("TEXTCOLOR", (3, 1), (3, 1), SEV_COLOR["medium"]),
            ("TEXTCOLOR", (6, 1), (6, 1), LEAF),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 1), (-1, 1), 8), ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#D1D5DB")),
        ]))
        story.append(t)

        # Fix first
        title = "Fix first" if c["first_run"] else "New since last run: fix first"
        story.append(Paragraph(title, H2))
        if not c["items"]:
            story.append(Paragraph("Nothing at high or medium priority. Good.", P))
        rows = []
        for it in c["items"]:
            sev = f'<font color="{SEV_COLOR[it["severity"]].hexval()}"><b>{it["severity"].upper()}</b></font>'
            cell = [Paragraph(f"{sev} · <b>{_esc(it['check'])}</b> · <font color='{TEAL.hexval()}'>{_esc(path_of(it['url']))}</font>", P),
                    Paragraph(_esc(it["message"]), SMALL)]
            adv = ADVICE.get(it["check"])
            if adv:
                cell.append(Paragraph(f"<i>What to do:</i> {_esc(adv)}", SMALL))
            rows.append([cell])
        if rows:
            t = Table(rows, colWidths=[7.0 * inch])
            t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")),
                                   ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
            story.append(t)

        # Lower priority, grouped
        if c["grouped_low"]:
            story.append(Paragraph("Lower priority, grouped by problem", H2))
            story.append(Paragraph("One line per kind of problem. Most of these are a single template fix that clears every page listed.", SMALL))
            rows = []
            for g in c["grouped_low"]:
                urls = ", ".join(_esc(path_of(u)) for u in g["urls"])
                more = f" and {g['count'] - len(g['urls'])} more" if g["count"] > len(g["urls"]) else ""
                rows.append([[Paragraph(f"<b>{_esc(g['check'])}</b> on {g['count']} page(s)", P),
                              Paragraph(f"e.g. {_esc(g['example'][:200])}", SMALL),
                              Paragraph(f"<font color='{TEAL.hexval()}'>{urls}</font>{more}", SMALL)]])
            t = Table(rows, colWidths=[7.0 * inch])
            t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")),
                                   ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
            story.append(t)

    H3 = ParagraphStyle("h3", parent=P, fontName=bold_font, spaceBefore=10, spaceAfter=4)

    def table(title, header, rows, widths):
        if not rows:
            return
        story.append(Paragraph(title, H3))
        data = [header] + rows
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), CREAM), ("FONTNAME", (0, 0), (-1, 0), bold_font),
                               ("FONTNAME", (0, 1), (-1, -1), body_font), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                               ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)

    def num(v):
        return "–" if v is None else f"{v:,}" if isinstance(v, int) else str(v)

    def signed(v):
        return "–" if v is None else f"{v:+,}"

    # Search Console
    g = d["gsc"]
    story.append(PageBreak())
    story.append(Paragraph("Google Search Console", H2))
    if not g.get("available"):
        story.append(Paragraph("Not connected yet. Once the service account is added to the Search Console property, "
                               "this page shows clicks, impressions, queries close to page one, and position drops.", P))
    else:
        story.append(Paragraph(f"Window: {g['window']}. Clicks <b>{g['clicks']}</b> ({g['clicks_delta']}), "
                               f"impressions <b>{g['impressions']}</b> ({g['impr_delta']}).", P))

        table("Close to page one (position 8 to 20, most impressions first)",
              ["Query", "Position", "Impressions", "Volume", "Page"],
              [[Paragraph(_esc(w["query"]), P), f"{w['position']}", f"{w['impressions']}",
                f"{w['volume']}" if w["volume"] else "–", Paragraph(_esc(path_of(w["page"])), MONO)] for w in g["wins"]],
              [2.3 * inch, 0.7 * inch, 0.9 * inch, 0.7 * inch, 2.4 * inch])
        table("Position drops (3+ places on queries with 100+ impressions)",
              ["Query", "Before", "After", "Impressions", "Page"],
              [[Paragraph(_esc(x["query"]), P), f"{x['before']}", f"{x['after']}", f"{x['impressions']}",
                Paragraph(_esc(path_of(x["page"])), MONO)] for x in g["drops"]],
              [2.3 * inch, 0.7 * inch, 0.7 * inch, 0.9 * inch, 2.4 * inch])
        table("New queries this period", ["Query", "Impressions", "Page"],
              [[Paragraph(_esc(x["query"]), P), f"{x['impressions']}", Paragraph(_esc(path_of(x["page"])), MONO)] for x in g["new_queries"]],
              [3.0 * inch, 1.0 * inch, 3.0 * inch])

    # Rankings (DataForSEO Labs)
    r = d.get("ranks") or {}
    story.append(PageBreak())
    story.append(Paragraph("Rankings", H2))
    if not r.get("available"):
        story.append(Paragraph("No rank data yet. Runs with KEYWORD_PROVIDER=dataforseo (`python -m seo ranks`).", P))
    else:
        n, b = r["now"], r["before"]
        intro = (f"As of {r['date']}: <b>{n['total']}</b> keywords ranking in the top 100, <b>{n['top10']}</b> on page one, "
                 f"<b>{n['top3']}</b> in the top 3.")
        if b:
            intro += (f" Compared with {r['baseline']}: page one {signed(n['top10'] - b['top10'])}, "
                      f"top 3 {signed(n['top3'] - b['top3'])}, total {signed(n['total'] - b['total'])}.")
        story.append(Paragraph(intro, P))
        kw_row = lambda x: [Paragraph(_esc(x["keyword"]), P), num(x.get("before")), num(x.get("position")),
                            num(x.get("volume") or None), Paragraph(_esc(path_of(x["url"] or "")), MONO)]
        widths = [2.4 * inch, 0.6 * inch, 0.6 * inch, 0.7 * inch, 2.7 * inch]
        hdr = ["Keyword", "Before", "Now", "Volume", "Page"]
        table(f"Moved up {MOVE_LABEL}", hdr, [kw_row(x) for x in r["up"]], widths)
        table(f"Moved down {MOVE_LABEL}", hdr, [kw_row(x) for x in r["down"]], widths)
        table("New to page one", hdr, [kw_row(x) for x in r["new_top10"]], widths)
        table("Fell off page one", hdr, [kw_row(x) for x in r["lost_page1"]], widths)
        if not any([r["up"], r["down"], r["new_top10"], r["lost_page1"]]) and b:
            story.append(Paragraph("No keyword moved 3 or more places since the baseline.", SMALL))
        table("Highest-volume keywords we rank for", ["Keyword", "Position", "Volume", "Page"],
              [[Paragraph(_esc(t.keyword), P), num(t.position), num(t.volume), Paragraph(_esc(path_of(t.url or "")), MONO)]
               for t in r["top"]], [2.6 * inch, 0.7 * inch, 0.8 * inch, 2.9 * inch])

    # Competitor gaps
    gp = d.get("gaps") or {}
    story.append(PageBreak())
    story.append(Paragraph("Competitor keyword gaps", H2))
    if not gp.get("available"):
        story.append(Paragraph("No gap data yet. Runs weekly, or with `python -m seo gaps`.", P))
    else:
        comps = ", ".join(f"{c} ({n})" for c, n in gp["per_competitor"].items())
        story.append(Paragraph(f"Keywords each competitor ranks top-20 for in US Google where labeffects.com does not rank at all, "
                               f"as of {gp['date']}: {_esc(comps)}. Treat these as topics to cover, not exact titles.", P))

        def comp_cell(m):
            return Paragraph("<br/>".join(f"{_esc(c['domain'])} #{c['position']}" for c in m["competitors"]), SMALL)

        gap_row = lambda m: [Paragraph(_esc(m["keyword"]), P), num(m["volume"] or None), num(m.get("difficulty")), comp_cell(m)]
        gw = [2.6 * inch, 0.8 * inch, 0.8 * inch, 2.8 * inch]
        table("Shared gaps (2 or more competitors rank, we do not)", ["Keyword", "Volume", "Difficulty", "Who ranks"],
              [gap_row(m) for m in gp["shared"]], gw)
        table("Biggest gaps by search volume", ["Keyword", "Volume", "Difficulty", "Who ranks"],
              [gap_row(m) for m in gp["top"]], gw)

    # Backlinks
    bl = d.get("backlinks") or {}
    story.append(PageBreak())
    story.append(Paragraph("Backlinks", H2))
    if not bl.get("available"):
        story.append(Paragraph("No backlink data yet. Runs nightly with DataForSEO (`python -m seo backlinks`).", P))
    else:
        s = f"As of {bl['date']}: <b>{num(bl['backlinks'])}</b> backlinks from <b>{num(bl['referring_domains'])}</b> referring domains"
        if bl["baseline"]:
            s += f" ({signed(bl['backlinks_delta'])} links, {signed(bl['domains_delta'])} domains since {bl['baseline']})"
        s += f". Domain rank {num(bl['rank'])}, broken backlinks {num(bl['broken'])}."
        story.append(Paragraph(s, P))
        dom_row = lambda x: [Paragraph(_esc(x["domain"]), P), num(x["rank"]), num(x["backlinks"]), x["first_seen"] or "–"]
        dw = [3.4 * inch, 0.9 * inch, 1.0 * inch, 1.7 * inch]
        hdr = ["Domain", "Rank", "Links", "First seen"]
        table("New referring domains", hdr, [dom_row(x) for x in bl["new"]], dw)
        table("Lost referring domains", hdr, [dom_row(x) for x in bl["lost"]], dw)
        table("Strongest referring domains", hdr, [dom_row(x) for x in bl["top"]], dw)

    story.append(Spacer(1, 18))
    story.append(Paragraph("Generated by the Lab Effects SEO monitor. Severity: high = broken or invisible to Google, "
                           "medium = costs rankings or trust, low = polish.", SMALL))

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(out_path, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            title=f"Lab Effects SEO report {d['date']}", author="Lab Effects SEO monitor")
    doc.build(story)
    return out_path
