"""Reports in every format: stable test ids, one case per message per subject."""

import csv
import io
import json

import pytest

from semcache.report import (
    FORMATS,
    Case,
    Report,
    item_id,
    parse_formats,
    test_id,
    write,
)


def case(subject, text, expected, actual, **kw):
    return Case(
        test_id=test_id("suite", subject, text), suite="suite", subject=subject,
        item_id=item_id(text), text=text, expected=expected, actual=actual,
        passed=expected == actual, **kw,
    )  # fmt: skip


def report():
    cases = [
        case("a", "diary apps", "search", "search", confidence=0.9, seconds=0.2),
        case("b", "diary apps", "search", "chat"),
        case("a", "rank | these", "analysis", "chat"),
        case("b", "rank | these", "analysis", "analysis"),
    ]
    return Report(
        title="T", suite="suite", meta={"date": "2026-01-01"},
        summary_headers=["Model", "Accuracy"], summary_rows=[["a", "50%"], ["b", "50%"]],
        cases=cases, notes=["a note"],
    )  # fmt: skip


def test_test_ids_are_stable_and_ignore_case_and_whitespace():
    assert test_id("s", "m", "Diary  Apps") == test_id("s", "m", "diary apps")
    assert test_id("s", "m", "x").startswith("s::m::") and len(item_id("x")) == 8
    assert item_id("diary apps") != item_id("rank these")


def test_formats_parse_with_aliases_and_reject_unknown_names():
    assert parse_formats("markdown, JSON") == ["md", "json"]
    assert parse_formats("all") == list(FORMATS)
    with pytest.raises(ValueError, match="xml"):
        parse_formats("md,xml")


def test_every_format_is_written_and_carries_the_test_ids(tmp_path):
    r = report()
    paths = write(r, list(FORMATS), tmp_path)
    assert sorted(p.suffix for p in paths) == [".csv", ".html", ".json", ".md", ".pdf"]
    ids = {c.test_id for c in r.cases}
    assert len(ids) == 4  # two messages x two subjects
    for p in paths:
        assert p.stat().st_size > 0
    for suffix in (".json", ".csv"):  # the machine-readable formats carry every case's id
        text = (tmp_path / f"report{suffix}").read_text()
        assert all(i in text for i in ids), suffix
    assert (tmp_path / "report.pdf").read_bytes().startswith(b"%PDF")


def test_json_has_totals_and_one_result_per_case(tmp_path):
    (path,) = write(report(), ["json"], tmp_path)
    doc = json.loads(path.read_text())
    assert doc["totals"] == {"cases": 4, "passed": 2, "failed": 2}
    assert [x["test_id"] for x in doc["results"]][0] == test_id("suite", "a", "diary apps")
    assert doc["results"][0]["confidence"] == 0.9 and doc["results"][1]["passed"] is False


def test_csv_round_trips_text_with_pipes_and_commas(tmp_path):
    (path,) = write(report(), ["csv"], tmp_path)
    rows = list(csv.DictReader(io.StringIO(path.read_text())))
    assert len(rows) == 4 and rows[2]["text"] == "rank | these"
    assert {r["passed"] for r in rows} == {"True", "False"}


def test_markdown_escapes_pipes_and_html_escapes_markup(tmp_path):
    r = report()
    r.cases.append(case("a", "<script>x</script>", "chat", "chat"))
    md_path, html_path = write(r, ["md", "html"], tmp_path)
    assert "rank \\| these" in md_path.read_text()
    page = html_path.read_text()
    assert "<script>x" not in page and "&lt;script&gt;" in page
    assert "prefers-color-scheme" in page


def test_markdown_lists_results_mistakes_and_disagreements(tmp_path):
    (path,) = write(report(), ["md"], tmp_path)
    md = path.read_text()
    assert "## Results by message" in md and "✓ search" in md and "✗ chat" in md
    assert "### a (1 failed)" in md and "## Where subjects disagree" in md
