import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

from semcache.manifest import MAX_TOPICS, build_entry, display_name, format_entry, topics_for

TODAY = date(2026, 10, 5)
AUTOMATISCH = {
    "name": "automatisch/automatisch", "description": "The open source Zapier alternative.",
    "services": "postgresql,valkey", "topics": "automation,zapier,workflow", "buildable": "ready",
}  # fmt: skip


def test_entry_matches_the_directory_conventions():
    entry, warnings = build_entry(AUTOMATISCH, TODAY)
    assert list(entry) == ["name", "owner", "repo", "added", "description", "topics"]
    assert entry["name"] == "Automatisch" and entry["owner"] == "automatisch"
    assert entry["added"] == "2026-10-05"
    # app name first, then Aiven services, then GitHub tags (like the existing entries)
    assert entry["topics"] == [
        "automatisch",
        "postgresql",
        "valkey",
        "automation",
        "zapier",
        "workflow",
    ]
    assert not any(
        "Dockerfile" in w or "Compose" in w for w in warnings
    )  # ready: no compose warning
    assert any("fork" in w.lower() for w in warnings)


def test_pasteable_text_is_valid_json_in_the_files_own_style():
    entry, _ = build_entry(AUTOMATISCH, TODAY)
    text = format_entry(entry)
    assert text.startswith('  {\n    "name": ') and text.endswith("\n  }")
    assert json.loads(text) == entry
    assert '"topics": ["automatisch", "postgresql"' in text  # one line, like the file
    # it must drop into the real array without breaking it
    assert isinstance(json.loads("[" + text + "]"), list)


def test_warnings_for_repos_that_are_not_ready():
    img = build_entry({**AUTOMATISCH, "buildable": "image-only"}, TODAY)[1]
    assert any("image: only" in w for w in img)
    legacy = build_entry({**AUTOMATISCH, "buildable": "no"}, TODAY)[1]  # old stored value
    assert any("image: only" in w for w in legacy)
    none = build_entry({**AUTOMATISCH, "buildable": "none"}, TODAY)[1]
    assert any("No Compose file" in w for w in none)


def test_sparse_data_still_gives_a_valid_entry():
    entry, _ = build_entry(
        {"name": "o/some_tool.js", "services": "unknown", "buildable": "none"}, TODAY
    )
    assert entry["name"] == "Some Tool Js" and entry["topics"] == ["some-tool-js"]
    assert "description" not in entry
    bare, _ = build_entry({"name": "o/r", "services": "none"}, TODAY)
    assert bare["topics"] == ["r"]


def test_topics_are_slugged_deduped_and_capped():
    t = topics_for("Dify", "postgresql,valkey", "LLM, ai agents,python,dify,llm,rag,extra")
    assert t[:3] == ["dify", "postgresql", "valkey"] and len(set(t)) == len(t)
    assert "ai-agents" in t and len(t) <= MAX_TOPICS
    assert topics_for("x", "none", "") == ["x"]


def test_display_name():
    assert display_name("flow-ctl") == "Flow Ctl" and display_name("LiteLLM") == "LiteLLM"


def test_bad_names_are_rejected():
    for bad in ("noslash", "a/b/c", ""):
        with pytest.raises(ValueError):
            build_entry({"name": bad}, TODAY)


def test_agrees_with_the_real_directory_schema_when_it_is_checked_out():
    path = Path.home() / "projects" / "runs-on-runtime" / "schema.py"
    if not path.exists():
        pytest.skip("runs-on-runtime is not checked out")
    spec = importlib.util.spec_from_file_location("ror_schema", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ror_schema"] = mod  # pydantic resolves the schema's forward references via this
    try:
        spec.loader.exec_module(mod)
        existing = json.loads((path.parent / "data" / "manifest.json").read_text())
        for owner in (None, "kjaymiller"):  # pointing at the upstream repo, and at your fork
            entry, _ = build_entry(AUTOMATISCH, TODAY, owner=owner)
            mod.validate_manifest([*existing, entry])  # raises if the entry would break the build
    finally:
        sys.modules.pop("ror_schema", None)


def test_fork_owner_override_and_links():
    from semcache.manifest import EDIT_MANIFEST_URL, fork_url

    entry, warnings = build_entry(AUTOMATISCH, TODAY, owner="kjaymiller")
    assert entry["owner"] == "kjaymiller" and entry["repo"] == "automatisch"
    assert any("your fork kjaymiller/automatisch" in w for w in warnings)
    plain, plain_warn = build_entry(AUTOMATISCH, TODAY)
    assert plain["owner"] == "automatisch" and any("Fork it" in w for w in plain_warn)
    assert fork_url("automatisch/automatisch") == "https://github.com/automatisch/automatisch/fork"
    assert (
        EDIT_MANIFEST_URL
        == "https://github.com/Aiven-Labs/runs-on-runtime/edit/main/data/manifest.json"
    )


def test_owner_override_is_validated():
    for bad in ("", "-bad", "bad-", "has space", "a/b", "x" * 40, "semi;colon", "../x"):
        with pytest.raises(ValueError, match="valid GitHub username"):
            build_entry(AUTOMATISCH, TODAY, owner=bad)
    assert build_entry(AUTOMATISCH, TODAY, owner="Aiven-Labs")[0]["owner"] == "Aiven-Labs"
