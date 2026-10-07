"""Which model makes each decision, and what the models cost: editable at runtime.

settings.toml holds the defaults. Edits made on the settings page are saved in Valkey (the
compose file mounts settings.toml read-only) and win over the file, so a restart keeps them.
The model list and prices import from CSV:

    model,input_per_mtok,output_per_mtok
    claude-haiku-4-5,$1.155/M,$5.775/M
    qwen3-32b,0.189,0.735

Prices are USD per million tokens; a leading `$` and a trailing `/M` are accepted.
"""

import csv
import io
import json
import re
import secrets

from .routes import ROUTES
from .tunables import ModelPrice, ModelsCfg, Tunables

CATALOG_KEY = "settings:models:catalog"  # hash: model name -> {"input": .., "output": ..}
ROLES_KEY = "settings:models:roles"  # hash: role -> model name ("" = no pin)
ROLES = ("hit", "classifier", "miss", "followup")
PIN_PREFIX = "pin:"
MAX_ROWS = 500

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,99}$")
_PRICE = re.compile(r"^\$?\s*(\d+(?:\.\d+)?|\.\d+)\s*(?:/\s*[mM](?:tok)?)?$")
_HEADERS = {
    "model": {"model", "name", "model_id", "id"},
    "input": {"input_per_mtok", "input", "input_price", "input_per_m", "input_usd_per_mtok"},
    "output": {"output_per_mtok", "output", "output_price", "output_per_m", "output_usd_per_mtok"},
}


class SettingsError(ValueError):
    """The edit was refused; the message says why, and nothing was saved."""


def parse_price(raw: str) -> float:
    m = _PRICE.match((raw or "").strip())
    if not m:
        raise ValueError(f"not a price: {raw!r}")
    return float(m.group(1))


def parse_models_csv(text: str) -> tuple[dict[str, ModelPrice], list[str]]:
    """({model: price}, errors). With any error, callers save nothing."""
    text = (text or "").strip("﻿ \r\n")
    if not text:
        return {}, ["the CSV is empty"]
    first = text.splitlines()[0]
    delimiter = "\t" if "\t" in first and "," not in first else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    head = [h.strip().lower() for h in next(reader, [])]
    cols = {
        field: next((i for i, h in enumerate(head) if h in names), None)
        for field, names in _HEADERS.items()
    }
    if None in cols.values():
        need = "model, input_per_mtok, output_per_mtok"
        return {}, [f"line 1: the header needs these columns: {need} (found: {', '.join(head)})"]
    rows: dict[str, ModelPrice] = {}
    errors: list[str] = []
    for n, row in enumerate(reader, start=2):
        if not any(c.strip() for c in row):
            continue
        try:
            name = row[cols["model"]].strip()
            if not _NAME.match(name):
                raise ValueError(f"bad model name {name!r}")
            if name in rows:
                raise ValueError(f"{name} appears twice")
            rows[name] = ModelPrice(
                input_per_mtok=parse_price(row[cols["input"]]),
                output_per_mtok=parse_price(row[cols["output"]]),
            )
        except (ValueError, IndexError) as e:
            errors.append(f"line {n}: {e if isinstance(e, ValueError) else 'too few columns'}")
    if len(rows) > MAX_ROWS:
        errors.append(f"too many models ({len(rows)}); the limit is {MAX_ROWS}")
    if not rows and not errors:
        errors.append("the CSV has a header but no models")
    return rows, errors


def to_csv(prices: dict[str, ModelPrice]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["model", "input_per_mtok", "output_per_mtok"])
    for name in sorted(prices):
        p = prices[name]
        w.writerow([name, p.input_per_mtok, p.output_per_mtok])
    return buf.getvalue()


def token_ok(supplied: str | None, expected: str | None) -> bool:
    """Constant-time check. No expected token means editing is switched off."""
    return bool(expected) and bool(supplied) and secrets.compare_digest(supplied, expected)


class ModelSettings:
    """Reads and writes the saved model list and role choices, and merges them over the file."""

    def __init__(self, client, tunables: Tunables):
        self.r, self.base = client, tunables

    @staticmethod
    def _s(v) -> str:
        return v.decode() if isinstance(v, bytes) else v

    def saved_prices(self) -> dict[str, ModelPrice]:
        out = {}
        for k, v in self.r.hgetall(CATALOG_KEY).items():
            d = json.loads(self._s(v))
            out[self._s(k)] = ModelPrice(input_per_mtok=d["input"], output_per_mtok=d["output"])
        return out

    def saved_roles(self) -> dict[str, str]:
        return {self._s(k): self._s(v) for k, v in self.r.hgetall(ROLES_KEY).items()}

    def prices(self) -> dict[str, ModelPrice]:
        """settings.toml prices with the saved ones on top."""
        return {**self.base.cost.models, **self.saved_prices()}

    def roles(self) -> dict[str, str]:
        """role -> model for hit, classifier, miss, followup and `pin:<route>`."""
        r = self.base.routing
        out = {
            "hit": r.models.hit, "classifier": r.models.classifier, "miss": r.models.miss,
            "followup": r.followup_model,
        }  # fmt: skip
        out |= {PIN_PREFIX + route: model for route, model in r.pin.items()}
        for k, v in self.saved_roles().items():
            if k.startswith(PIN_PREFIX) and not v:
                out.pop(k, None)  # a saved empty pin removes the file's pin
            else:
                out[k] = v
        return out

    def effective(self) -> tuple[dict[str, ModelPrice], ModelsCfg, str, dict[str, str]]:
        """(prices, models, followup model, pins) as the chat service should use them."""
        roles = self.roles()
        pins = {k[len(PIN_PREFIX) :]: v for k, v in roles.items() if k.startswith(PIN_PREFIX)}
        models = ModelsCfg(hit=roles["hit"], classifier=roles["classifier"], miss=roles["miss"])
        return self.prices(), models, roles["followup"], pins

    # ---- edits: validate everything first, then write --------------------------------------------
    def save_roles(self, choices: dict[str, str]) -> None:
        """`choices` maps role (or `pin:<route>`) to a model; an empty pin clears it."""
        prices = self.prices()
        clean: dict[str, str] = {}
        for key, model in choices.items():
            model = (model or "").strip()
            if key in ROLES:
                if not model:
                    raise SettingsError(f"choose a model for {key}")
            elif key.startswith(PIN_PREFIX):
                if key[len(PIN_PREFIX) :] not in ROUTES:
                    raise SettingsError(f"{key[len(PIN_PREFIX) :]} is not a route")
            else:
                raise SettingsError(f"unknown decision: {key}")
            if model and model not in prices:
                raise SettingsError(f"{model} is not in the model list; add it with the CSV first")
            clean[key] = model
        if clean:
            self.r.hset(ROLES_KEY, mapping=clean)

    def import_csv(self, text: str, *, replace: bool = False) -> int:
        """Add or update models from CSV. `replace` first drops every saved model (the ones in
        settings.toml stay). Refuses if that would remove a model a decision is using."""
        rows, errors = parse_models_csv(text)
        if errors:
            raise SettingsError("; ".join(errors[:5]) + (" ..." if len(errors) > 5 else ""))
        if replace:
            gone = set(self.saved_prices()) - set(rows) - set(self.base.cost.models)
            self._refuse_if_used(gone)
        pipe = self.r.pipeline()
        if replace:
            pipe.delete(CATALOG_KEY)
        pipe.hset(
            CATALOG_KEY,
            mapping={
                k: json.dumps({"input": p.input_per_mtok, "output": p.output_per_mtok})
                for k, p in rows.items()
            },
        )
        pipe.execute()
        return len(rows)

    def delete_model(self, name: str) -> None:
        if name not in self.saved_prices():
            raise SettingsError(f"{name} is not a saved model (models from settings.toml stay)")
        self._refuse_if_used({name})
        self.r.hdel(CATALOG_KEY, name)

    def _refuse_if_used(self, names: set[str]) -> None:
        used = {m for m in self.roles().values() if m}
        clash = sorted(names & used)
        if clash:
            raise SettingsError(f"{', '.join(clash)} is in use; pick another model for it first")
