"""The settings page: pick the model for each decision, and edit the model list from CSV.

Reading is open (it shows what the app is configured to use). Every change needs the admin token
(SEMCACHE_ADMIN_TOKEN); with none set the page is read-only. Changes are saved in Valkey and
applied to the running chat service, so no restart is needed.
"""

import logging
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .model_settings import PIN_PREFIX, ROLES, ModelSettings, SettingsError, to_csv, token_ok
from .routes import ROUTES

log = logging.getLogger("uvicorn.error")
router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

MAX_UPLOAD = 256 * 1024
ROLE_INFO = {
    "hit": ("Hit", "Answers when the router matched, or the cache already covers the question. "
            "Pick the cheapest model that is good enough."),
    "classifier": ("Fallback classifier", "Reads a message the router could not place when Jev "
                   "is off or unsure, and answers when the classifier is down."),
    "miss": ("Miss", "Live GitHub data or real reasoning. Also the price baseline for "
             "\"saved by routing\"."),
    "followup": ("Follow-up", "Short follow-ups in an ongoing chat (\"so Dify uses vite?\")."),
}  # fmt: skip


def _back(msg: str = "", err: str = "") -> RedirectResponse:
    key, text = ("err", err) if err else ("ok", msg)
    return RedirectResponse(f"/settings?{key}={quote_plus(text[:300])}", status_code=303)


def _guard(request: Request, token: str | None) -> str:
    """An error message if this edit may not proceed, else ''."""
    expected = getattr(request.app.state, "admin_token", None)
    if not expected:
        return "Editing is off. Set SEMCACHE_ADMIN_TOKEN and restart the app to turn it on."
    if not token_ok(token, expected):
        return "That admin token is not right. Nothing was changed."
    return ""


def _apply(request: Request) -> None:
    st = request.app.state
    prices, models, followup, pins = st.model_settings.effective()
    st.chat.apply_models(models, pins, followup, prices)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, ok: str = "", err: str = ""):
    st = request.app.state
    ms: ModelSettings = st.model_settings
    prices, roles, saved = ms.prices(), ms.roles(), ms.saved_prices()
    gateway = getattr(st, "gateway_models", None)
    used = {m for m in roles.values() if m}
    models = [
        {
            "name": n, "input": p.input_per_mtok, "output": p.output_per_mtok,
            "source": "saved here" if n in saved else "settings.toml", "used": n in used,
            "deletable": n in saved and n not in used,
            "missing": gateway is not None and n not in gateway,
        }
        for n, p in sorted(prices.items())
    ]  # fmt: skip
    ctx = {
        "roles": [(k, *ROLE_INFO[k], roles.get(k, "")) for k in ROLES],
        "pins": [(r, roles.get(PIN_PREFIX + r, "")) for r in ROUTES],
        "model_names": sorted(prices),
        "models": models,
        "jev": {
            "model": st.chat.jev.model if getattr(st.chat, "jev", None) else "",
            "min_confidence": st.chat.jev.min_confidence if getattr(st.chat, "jev", None) else 0,
        },
        "editable": bool(getattr(st, "admin_token", None)),
        "gateway_known": gateway is not None,
        "ok": ok, "err": err,
    }  # fmt: skip
    return templates.TemplateResponse(request, "settings.html", ctx)


@router.get("/settings/models.csv")
def models_csv(request: Request):
    body = to_csv(request.app.state.model_settings.prices())
    return Response(
        body, media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="models.csv"'},
    )  # fmt: skip


@router.post("/settings/roles")
async def save_roles(request: Request):
    form = await request.form()
    if msg := _guard(request, form.get("token")):
        return _back(err=msg)
    choices = {k: str(form.get(k, "")) for k in ROLES}
    choices |= {PIN_PREFIX + r: str(form.get("pin_" + r, "")) for r in ROUTES}
    try:
        request.app.state.model_settings.save_roles(choices)
    except SettingsError as e:
        return _back(err=str(e))
    _apply(request)
    log.info("settings: model choices changed")
    return _back("Saved. The new models apply to the next message.")


@router.post("/settings/models/import")
async def import_models(request: Request):
    form = await request.form()
    if msg := _guard(request, form.get("token")):
        return _back(err=msg)
    text = str(form.get("csv_text") or "")
    upload = form.get("csv_file")
    if upload is not None and getattr(upload, "filename", ""):
        raw = await upload.read(MAX_UPLOAD + 1)
        if len(raw) > MAX_UPLOAD:
            return _back(err="That file is too large (256 KB limit).")
        text = raw.decode("utf-8", errors="replace")
    try:
        n = request.app.state.model_settings.import_csv(text, replace=form.get("mode") == "replace")
    except SettingsError as e:
        return _back(err=f"Nothing imported. {e}")
    _apply(request)
    log.info("settings: imported %d models", n)
    return _back(f"Imported {n} model{'s' if n != 1 else ''}.")


@router.post("/settings/models/delete")
async def delete_model(request: Request):
    form = await request.form()
    if msg := _guard(request, form.get("token")):
        return _back(err=msg)
    name = str(form.get("name") or "")
    try:
        request.app.state.model_settings.delete_model(name)
    except SettingsError as e:
        return _back(err=str(e))
    _apply(request)
    return _back(f"Removed {name}.")
