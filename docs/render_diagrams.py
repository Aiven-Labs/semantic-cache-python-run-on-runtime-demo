"""Render every ```mermaid block in docs/flow.md to docs/img/NN-slug.png.

Needs node: it runs @mermaid-js/mermaid-cli through npx (the first run downloads Chromium).
Run with `mise run diagrams`.
"""

import re
import subprocess
import tempfile
from pathlib import Path

DOCS = Path(__file__).parent
OUT = DOCS / "img"


def blocks(text: str):
    """Yield (heading, mermaid source) for each diagram, headed by the section above it."""
    heading = ""
    for m in re.finditer(r"^## ([^\n]+)$|^```mermaid\n(.*?)^```", text, re.S | re.M):
        if m.group(1):
            heading = m.group(1)
        else:
            yield heading, m.group(2)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    with tempfile.TemporaryDirectory() as tmp:
        for heading, src in blocks((DOCS / "flow.md").read_text()):
            num, title = heading.split(". ", 1)
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            name = f"{int(num):02d}-{slug}"
            mmd = Path(tmp) / f"{name}.mmd"
            mmd.write_text(src)
            subprocess.run(
                ["npx", "-y", "@mermaid-js/mermaid-cli", "-i", str(mmd),
                 "-o", str(OUT / f"{name}.png"), "-s", "2", "-b", "white"],
                check=True,
            )  # fmt: skip
            print("wrote", OUT / f"{name}.png")


if __name__ == "__main__":
    main()
