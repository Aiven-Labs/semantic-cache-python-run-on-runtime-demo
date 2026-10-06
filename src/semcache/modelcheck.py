"""Check at startup that every model named in settings.toml exists on the gateway.

A model the gateway does not serve fails with "no healthy deployments" only when a chat first
needs it. Checking up front turns that into a warning in the log and in /healthz.
"""

import httpx

from .tunables import Tunables


def configured_models(t: Tunables) -> set[str]:
    """Every chat model the settings can select."""
    r = t.routing
    names = {r.models.hit, r.models.classifier, r.models.miss, r.followup_model, *r.pin.values()}
    if r.plan_routes:  # the free-model planner is only used when some route turns it on
        names.add(r.planner_model)
    return names


def gateway_models(
    base_url: str, api_key: str, client: httpx.Client | None = None
) -> set[str] | None:
    """Model ids the gateway serves, or None if it could not be asked (network, auth)."""
    own = client is None
    client = client or httpx.Client(timeout=5)
    try:
        r = client.get(
            f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"}
        )
        r.raise_for_status()
        return {m["id"] for m in r.json()["data"]}
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None
    finally:
        if own:
            client.close()


def check(t: Tunables, base_url: str, api_key: str, client: httpx.Client | None = None) -> dict:
    """{"checked": bool, "missing": [names]} for /healthz and the startup log."""
    available = gateway_models(base_url, api_key, client)
    if available is None:
        return {"checked": False, "missing": []}
    return {"checked": True, "missing": sorted(configured_models(t) - available)}
