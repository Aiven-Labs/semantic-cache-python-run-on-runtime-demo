import httpx
import pytest

from semcache.followups import STARTERS, build_suggestions
from semcache.github import _check, list_dir, read_file


def mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_check_rejects_bad_input():
    assert _check("grafana/grafana", "/docker/compose.yaml/") == "docker/compose.yaml"
    for repo in ("nope", "a/b/c", "../x/y", "a/b;rm", "", "../x", "x/..", "./x", "x/."):
        with pytest.raises(ValueError):
            _check(repo, "")
    for path in ("../etc/passwd", "a/../../b", "a?b=c", "a\nb"):
        with pytest.raises(ValueError):
            _check("a/b", path)


def test_list_dir_sorts_and_caps():
    items = [
        {"name": "z.md", "type": "file", "size": 5},
        {"name": "src", "type": "dir"},
        {"name": "Dockerfile", "type": "file", "size": 9},
    ]
    c = mock(lambda r: httpx.Response(200, json=items))
    rows = list_dir("a/b", client=c)
    assert [r["name"] for r in rows] == ["src", "Dockerfile", "z.md"]
    many = [{"name": f"f{i}", "type": "file", "size": 1} for i in range(300)]
    assert len(list_dir("a/b", client=mock(lambda r: httpx.Response(200, json=many)))) == 100


def test_list_dir_errors():
    with pytest.raises(ValueError, match="not found"):
        list_dir("a/b", client=mock(lambda r: httpx.Response(404)))
    with pytest.raises(RuntimeError, match="rate limit"):
        list_dir("a/b", client=mock(lambda r: httpx.Response(403)))


def test_read_file_truncates_and_detects_binary():
    big = mock(lambda r: httpx.Response(200, content=b"x" * 50_000))
    out = read_file("a/b", "f.txt", client=big, max_bytes=1000)
    assert out.startswith("x" * 1000) and "truncated at 1000" in out
    assert (
        read_file(
            "a/b", "i.png", client=mock(lambda r: httpx.Response(200, content=b"\x89PNG\0\0"))
        )
        == "(binary file, not shown)"
    )
    with pytest.raises(ValueError, match="file not found"):
        read_file("a/b", "nope", client=mock(lambda r: httpx.Response(404)))
    with pytest.raises(ValueError):
        read_file("a/b", "", client=big)


def test_read_file_uses_default_branch_url():
    seen = []
    read_file(
        "a/b",
        "docker/compose.yaml",
        client=mock(lambda r: (seen.append(str(r.url)), httpx.Response(200, content=b"ok"))[1]),
    )
    assert seen == ["https://raw.githubusercontent.com/a/b/HEAD/docker/compose.yaml"]


def test_suggestions_from_results():
    repos = [{"name": "o/one"}, {"name": "o/two"}, {"name": "o/one"}]
    s = build_suggestions(repos)
    assert (
        s[0] == "Look at the files in o/one"
        and "Compare o/one and o/two as template candidates" in s
    )
    assert len(s) <= 4 and len(set(s)) == len(s)


def test_suggestions_after_inspecting():
    s = build_suggestions([{"name": "o/one"}, {"name": "o/one", "inspected": True}])
    assert s[0].startswith("Is o/one ready for Aiven Runtime")
    assert not any(x.startswith("Look at the files") for x in s)


def test_suggestions_fall_back_to_starters():
    assert build_suggestions([]) == STARTERS
