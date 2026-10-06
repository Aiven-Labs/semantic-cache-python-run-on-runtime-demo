"""Backfill repos already in the index: re-look for a Compose file with the wider path list, and
fill in language / license / last push that older entries lack.

    docker compose exec app python -m semcache.recheck [--max-api 40]

Compose files are fetched from raw.githubusercontent.com (no API quota). Metadata uses one GitHub
API call per repo, so it is capped by --max-api (the unauthenticated limit is 60 per hour).
"""

import argparse
from concurrent.futures import ThreadPoolExecutor

import httpx
import valkey

from .compose import NONE, compose_status, normalize_compose
from .config import settings
from .github import _fetch_compose, _headers


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-api", type=int, default=40, help="max GitHub API calls for metadata")
    args = ap.parse_args()

    r = valkey.from_url(settings.valkey_url, decode_responses=True)
    prefix = f"{settings.catalog_prefix}candidate:"
    keys = {k: r.hget(k, "name") for k in r.scan_iter(f"{prefix}*")}
    keys = {k: n for k, n in keys.items() if n}

    with httpx.Client(timeout=10, headers=_headers(settings.github_token)) as gh:
        # 1. Compose: re-check repos with none, in parallel (raw.githubusercontent, no API quota).
        todo = [k for k in keys if normalize_compose(r.hget(k, "buildable")) == NONE]
        with ThreadPoolExecutor(max_workers=12) as pool:
            infos = list(pool.map(lambda k: _fetch_compose(gh, keys[k], "HEAD"), todo))
        fixed = 0
        for k, info in zip(todo, infos, strict=True):
            if info is not None:
                r.hset(
                    k,
                    mapping={
                        "buildable": compose_status(info),
                        "services": ",".join(info.services) or "none",
                        "compose_path": info.path,
                        "app_services": ",".join(info.app_services),
                        "image_apps": ",".join(info.image_only_apps),
                    },
                )
                fixed += 1

        # 2. Metadata: one API call per repo, capped.
        filled, left = 0, args.max_api
        for k, name in keys.items():
            if left <= 0:
                break
            if r.hget(k, "language") is not None:
                continue
            left -= 1
            try:
                resp = gh.get(f"https://api.github.com/repos/{name}")
            except httpx.HTTPError:
                continue
            if resp.status_code in (403, 429):
                print("GitHub rate limit reached; set GITHUB_TOKEN or re-run later")
                break
            if resp.status_code == 200:
                d = resp.json()
                lic = ((d.get("license") or {}).get("spdx_id") or "").replace("NOASSERTION", "")
                r.hset(
                    k,
                    mapping={
                        "language": d.get("language") or "",
                        "license": lic,
                        "pushed": (d.get("pushed_at") or "")[:10],
                    },
                )
                filled += 1
    print(f"checked {len(todo)} repos with no Compose: found {fixed}; metadata: {filled}")


if __name__ == "__main__":
    main()
