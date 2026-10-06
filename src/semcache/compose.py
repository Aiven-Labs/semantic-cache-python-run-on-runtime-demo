"""Decide how a repo's Compose file would land on Aiven Runtime.

Rules mirror Runtime's detection: a service with `build:` is an application; a service with a
recognized `image:` is a data service Aiven replaces.
"""

from dataclasses import dataclass, field

import yaml

# (substring of image name, Aiven service tag)
_DATA_IMAGES = [
    ("postgres", "postgresql"),
    ("kafka", "kafka"),
    ("valkey", "valkey"),
    ("redis", "valkey"),
    ("opensearch", "opensearch"),
]

_NAMES = ["docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml"]
_DIRS = ["", "docker/", "deploy/", "deployment/", "deployments/", "docker-compose/", "compose/"]
# Root first (by far the most common), then the usual subfolders.
COMPOSE_PATHS = [d + n for d in _DIRS for n in _NAMES]

# What the app stores for each repo, and what it means.
READY, IMAGE_ONLY, NONE = "ready", "image-only", "none"
COMPOSE_LABELS = {
    READY: "Compose file with a build: service (Runtime-ready)",
    IMAGE_ONLY: "Compose file found, but its app uses image: only (needs a Dockerfile)",
    NONE: "no Compose file found",
}
_LEGACY = {"yes": READY, "no": IMAGE_ONLY, "no compose": NONE}  # values stored before the rename


def normalize_compose(value: str | None) -> str:
    v = (value or "").strip()
    return v if v in COMPOSE_LABELS else _LEGACY.get(v, NONE)


def compose_status(info: "ComposeInfo | None") -> str:
    if info is None:
        return NONE
    return READY if info.buildable else IMAGE_ONLY


@dataclass
class ComposeInfo:
    services: list[str] = field(default_factory=list)  # Aiven data services detected
    app_services: list[str] = field(default_factory=list)  # services with build:
    image_only_apps: list[str] = field(default_factory=list)  # unrecognized image: (no build)
    path: str = ""  # where in the repo the file was found
    raw: str = ""  # the file text, as read_file would return it (truncated)

    @property
    def buildable(self) -> bool:
        return bool(self.app_services)


def analyze(compose_text: str) -> ComposeInfo | None:
    try:
        doc = yaml.safe_load(compose_text)
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict):
        return None

    info = ComposeInfo()
    for name, spec in doc["services"].items():
        if not isinstance(spec, dict):
            continue
        if "build" in spec:
            info.app_services.append(name)
            continue
        image = str(spec.get("image", "")).lower()
        tag = next((t for key, t in _DATA_IMAGES if key in image), None)
        if tag:
            if tag not in info.services:
                info.services.append(tag)
        elif image:
            info.image_only_apps.append(name)
    return info
