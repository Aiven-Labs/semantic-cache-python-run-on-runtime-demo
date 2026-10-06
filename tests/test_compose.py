from semcache.compose import analyze

SAMPLE = """
services:
  web:
    build: .
  db:
    image: postgres:16
  cache:
    image: bitnami/redis:7
  worker:
    image: ghcr.io/acme/worker:latest
"""


def test_analyze_detects_services():
    info = analyze(SAMPLE)
    assert info.services == ["postgresql", "valkey"]
    assert info.app_services == ["web"]
    assert info.image_only_apps == ["worker"]
    assert info.buildable


def test_image_only_not_buildable():
    info = analyze("services:\n  app:\n    image: acme/app\n")
    assert not info.buildable


def test_invalid():
    assert analyze("not: [valid") is None
    assert analyze("foo: bar") is None
