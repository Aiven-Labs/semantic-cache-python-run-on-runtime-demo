"""Test-run reports in several formats, each case carrying a stable test id.

Build a `Report` (a summary table plus one `Case` per message per subject), then write it as
json, csv, html, pdf or markdown with `write`. The test id is `suite::subject::item`, where the
item id is the first 8 hex digits of the message's SHA-256, so the same message keeps the same id
across runs, files and formats. PDF needs the optional `report` extra (reportlab).
"""

import csv
import hashlib
import html
import io
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

FORMATS = ("json", "csv", "html", "pdf", "md")
ALIASES = {"markdown": "md"}
EXTENSIONS = {"json": "json", "csv": "csv", "html": "html", "pdf": "pdf", "md": "md"}


def item_id(text: str) -> str:
    """Stable id for a message: same text, same id (whitespace and case are ignored)."""
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()[:8]


def test_id(suite: str, subject: str, text: str) -> str:
    return f"{suite}::{subject}::{item_id(text)}"


test_id.__test__ = False  # pytest: a helper that happens to start with "test_", not a test


@dataclass(frozen=True)
class Case:
    test_id: str
    suite: str
    subject: str  # the model or strategy under test
    item_id: str
    text: str
    expected: str
    actual: str
    passed: bool
    in_scope: bool = True
    confidence: float | None = None
    seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class Report:
    title: str
    suite: str
    meta: dict
    summary_headers: list[str]
    summary_rows: list[list[str]]
    cases: list[Case]
    notes: list[str] = field(default_factory=list)

    @property
    def subjects(self) -> list[str]:
        return list(dict.fromkeys(c.subject for c in self.cases))

    def by_item(self) -> list[tuple[str, list[Case]]]:
        """(item id, its case for each subject), in the order the items were run."""
        grouped: dict[str, list[Case]] = {}
        for c in self.cases:
            grouped.setdefault(c.item_id, []).append(c)
        return list(grouped.items())

    def failures(self, subject: str) -> list[Case]:
        return [c for c in self.cases if c.subject == subject and not c.passed]

    def disagreements(self) -> list[list[Case]]:
        return [cs for _, cs in self.by_item() if len({c.actual for c in cs}) > 1]


# ---- renderers ---------------------------------------------------------------------------------
def to_json(r: Report) -> str:
    total = len(r.cases)
    passed = sum(c.passed for c in r.cases)
    doc = {
        "title": r.title, "suite": r.suite, "meta": r.meta,
        "totals": {"cases": total, "passed": passed, "failed": total - passed},
        "summary": {"headers": r.summary_headers, "rows": r.summary_rows},
        "results": [asdict(c) for c in r.cases],
        "notes": r.notes,
    }  # fmt: skip
    return json.dumps(doc, indent=1)


def to_csv(r: Report) -> str:
    buf = io.StringIO()
    cols = list(asdict(r.cases[0])) if r.cases else []
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for c in r.cases:
        w.writerow(asdict(c))
    return buf.getvalue()


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(_md_cell(str(v)) for v in row) + " |" for row in rows]
    return out


def to_md(r: Report) -> str:
    subjects = r.subjects
    lines = [f"# {r.title}", "", " · ".join(f"{k}: {v}" for k, v in r.meta.items()), ""]
    lines += ["## Summary", "", *_md_table(r.summary_headers, r.summary_rows), ""]
    lines += ["## Results by message", "", "✓ passed, ✗ failed. Each cell shows the answer.", ""]
    rows = []
    for iid, cs in r.by_item():
        first = cs[0]
        cells = {c.subject: f"{'✓' if c.passed else '✗'} {c.actual}" for c in cs}
        rows.append(
            [f"`{iid}`", first.text, first.expected]
            + [cells.get(s, "") for s in subjects]
        )  # fmt: skip
    lines += _md_table(["id", "message", "expected", *subjects], rows)
    lines += ["", "Test ids are `" + f"{r.suite}::<subject>::<id>`.", "", "## Mistakes by subject"]
    for s in subjects:
        bad = r.failures(s)
        lines += ["", f"### {s} ({len(bad)} failed)", ""]
        lines += [f"- `{c.test_id}` \"{c.text}\": expected {c.expected}, got {c.actual}"
                  + (f", confidence {c.confidence:.2f}" if c.confidence is not None else "")
                  for c in bad] or ["None."]  # fmt: skip
    lines += ["", "## Where subjects disagree", ""]
    dis = r.disagreements()
    for cs in dis:
        got = ", ".join(f"{c.subject}: {c.actual}" for c in cs)
        lines.append(f'- `{item_id(cs[0].text)}` "{cs[0].text}" (expected {cs[0].expected}): {got}')
    if not dis:
        lines.append("They agree on every message.")
    if r.notes:
        lines += ["", "## Notes", "", *[f"- {n}" for n in r.notes]]
    return "\n".join(lines) + "\n"


_CSS = """
:root{--bg:#fff;--fg:#1c1c1e;--mute:#6b6b70;--line:#e3e3e8;--ok:#1a7f37;--bad:#c62828;
--okbg:#e8f5ec;--badbg:#fdecea}
@media (prefers-color-scheme:dark){:root{--bg:#161618;--fg:#ececf0;--mute:#9a9aa3;
--line:#2e2e33;--ok:#4cc16d;--bad:#ff7b72;--okbg:#14301d;--badbg:#3a1a18}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;
max-width:1200px;padding:24px 16px}
h1{margin:0 0 4px}p.meta{color:var(--mute);margin:0 0 24px}
table{border-collapse:collapse;width:100%;margin:8px 0 28px;font-size:14px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{position:sticky;top:0;background:var(--bg)}
td.ok{background:var(--okbg);color:var(--ok)}td.bad{background:var(--badbg);color:var(--bad)}
code{font-size:12px;color:var(--mute)}.scroll{overflow-x:auto}
"""


def to_html(r: Report) -> str:
    e = html.escape
    subjects = r.subjects
    out = [
        "<!doctype html><html lang=en><meta charset=utf-8>",
        "<meta name=viewport content='width=device-width,initial-scale=1'>",
        f"<title>{e(r.title)}</title><style>{_CSS}</style><body>",
        f"<h1>{e(r.title)}</h1>",
        "<p class=meta>" + e(" · ".join(f"{k}: {v}" for k, v in r.meta.items())) + "</p>",
        "<h2>Summary</h2><div class=scroll><table><tr>",
        "".join(f"<th>{e(h)}</th>" for h in r.summary_headers) + "</tr>",
    ]
    for row in r.summary_rows:
        out.append("<tr>" + "".join(f"<td>{e(str(v))}</td>" for v in row) + "</tr>")
    out += ["</table></div>", "<h2>Results by message</h2><div class=scroll><table><tr>"]
    out.append("<th>id</th><th>message</th><th>expected</th>")
    out.append("".join(f"<th>{e(s)}</th>" for s in subjects) + "</tr>")
    for iid, cs in r.by_item():
        by = {c.subject: c for c in cs}
        out.append(
            f"<tr><td><code>{iid}</code></td><td>{e(cs[0].text)}</td><td>{e(cs[0].expected)}</td>"
        )
        for s in subjects:
            c = by.get(s)
            if c is None:
                out.append("<td></td>")
                continue
            mark = "✓" if c.passed else "✗"
            tone = "ok" if c.passed else "bad"
            out.append(f"<td class={tone} title='{e(c.test_id)}'>{mark} {e(c.actual)}</td>")
        out.append("</tr>")
    out.append("</table></div>")
    out.append("<h2>Mistakes</h2>")
    for s in subjects:
        bad = r.failures(s)
        out.append(f"<h3>{e(s)} ({len(bad)} failed)</h3><ul>")
        for c in bad:
            conf = f", confidence {c.confidence:.2f}" if c.confidence is not None else ""
            out.append(
                f"<li><code>{e(c.test_id)}</code> “{e(c.text)}”: expected {e(c.expected)}, "
                f"got {e(c.actual)}{conf}</li>"
            )
        out.append("</ul>" if bad else "<li>None.</li></ul>")
    if r.notes:
        out.append("<h2>Notes</h2><ul>" + "".join(f"<li>{e(n)}</li>" for n in r.notes) + "</ul>")
    return "".join(out) + "</body></html>"


def to_pdf(r: Report) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as err:  # pragma: no cover - exercised only without the extra
        raise RuntimeError("PDF needs reportlab: uv sync --extra report") from err
    styles = getSampleStyleSheet()
    cell = styles["BodyText"].clone("cell", fontSize=7, leading=8.5)
    P = lambda t: Paragraph(html.escape(str(t)), cell)  # noqa: E731
    base = [
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=24, rightMargin=24,
                            topMargin=24, bottomMargin=24, title=r.title)  # fmt: skip
    meta_line = " · ".join(f"{k}: {v}" for k, v in r.meta.items())
    story = [
        Paragraph(html.escape(r.title), styles["Title"]),
        Paragraph(html.escape(meta_line), styles["Normal"]),
        Spacer(1, 10), Paragraph("Summary", styles["Heading2"]),
    ]  # fmt: skip
    summary = [[P(h) for h in r.summary_headers]] + [[P(v) for v in row] for row in r.summary_rows]
    story += [Table(summary, repeatRows=1, style=TableStyle(base)), Spacer(1, 12)]
    story.append(Paragraph("Results by message (✓ passed, ✗ failed)", styles["Heading2"]))
    subjects = r.subjects
    rows = [[P("id"), P("message"), P("expected"), *[P(s) for s in subjects]]]
    marks = []
    for n, (iid, cs) in enumerate(r.by_item(), start=1):
        by = {c.subject: c for c in cs}
        rows.append(
            [P(iid), P(cs[0].text), P(cs[0].expected)]
            + [P(f"{'PASS' if by[s].passed else 'FAIL'} {by[s].actual}") if s in by else P("")
               for s in subjects]
        )  # fmt: skip
        for col, s in enumerate(subjects, start=3):
            if s in by:
                tone = colors.HexColor("#e8f5ec" if by[s].passed else "#fdecea")
                marks.append(("BACKGROUND", (col, n), (col, n), tone))
    story.append(Table(rows, repeatRows=1, style=TableStyle(base + marks)))
    if r.notes:
        story += [Spacer(1, 12), Paragraph("Notes", styles["Heading2"])]
        story += [Paragraph("• " + html.escape(n), styles["Normal"]) for n in r.notes]
    doc.build(story)
    return buf.getvalue()


RENDERERS = {"json": to_json, "csv": to_csv, "html": to_html, "pdf": to_pdf, "md": to_md}


def parse_formats(spec: str) -> list[str]:
    """'md,json' or 'all' -> validated format names. Unknown names raise ValueError."""
    names = (
        FORMATS if spec.strip().lower() == "all" else [s.strip().lower() for s in spec.split(",")]
    )
    out = [ALIASES.get(n, n) for n in names if n]
    bad = [n for n in out if n not in RENDERERS]
    if bad:
        raise ValueError(f"unknown format {bad}; choose from {', '.join(FORMATS)} or 'all'")
    return list(dict.fromkeys(out))


def write(report: Report, formats: list[str], out_dir: Path, stem: str = "report") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for fmt in formats:
        body = RENDERERS[fmt](report)
        path = out_dir / f"{stem}.{EXTENSIONS[fmt]}"
        path.write_bytes(body if isinstance(body, bytes) else body.encode())
        paths.append(path)
    return paths
