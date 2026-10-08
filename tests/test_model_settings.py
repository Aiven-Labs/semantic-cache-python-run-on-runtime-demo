"""Model choices and prices edited at runtime: CSV parsing, saving, hot-swapping, the page."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from semcache.cost import Pricing
from semcache.model_settings import (
    CATALOG_KEY,
    ModelSettings,
    SettingsError,
    parse_models_csv,
    parse_price,
    to_csv,
    token_ok,
)
from semcache.settings_page import router
from semcache.tunables import ModelPrice, load_tunables


class FakeValkey:
    """Just enough of a Valkey client: hashes and a no-op pipeline."""

    def __init__(self):
        self.h: dict[str, dict] = {}

    def hgetall(self, k):
        return dict(self.h.get(k, {}))

    def hset(self, k, mapping):
        self.h.setdefault(k, {}).update(mapping)

    def hdel(self, k, name):
        self.h.get(k, {}).pop(name, None)

    def delete(self, k):
        self.h.pop(k, None)

    def pipeline(self):
        outer, ops = self, []

        class Pipe:
            def delete(self, k):
                ops.append(lambda: outer.delete(k))

            def hset(self, k, mapping):
                ops.append(lambda: outer.hset(k, mapping))

            def execute(self):
                for op in ops:
                    op()

        return Pipe()


@pytest.fixture
def base():
    return load_tunables("settings.toml")


@pytest.fixture
def ms(base):
    return ModelSettings(FakeValkey(), base)


# ---- CSV ------------------------------------------------------------------------------------------
def test_prices_accept_dollar_signs_and_per_million_suffixes():
    assert parse_price("1.155") == 1.155
    assert parse_price(" $5.775/M ") == 5.775
    assert parse_price("$.5 / m") == 0.5
    for bad in ("", "free", "-1", "1,5", "$1.2.3"):
        with pytest.raises(ValueError):
            parse_price(bad)


def test_csv_parses_header_aliases_extra_columns_and_tabs():
    rows, errors = parse_models_csv(
        "Model,Provider,Input,Output\nclaude-haiku-4-5,Anthropic,$1.155/M,$5.775/M\nqwen3-32b,Aiven,0.189,0.735\n"
    )
    assert errors == [] and rows["qwen3-32b"].output_per_mtok == 0.735
    rows, errors = parse_models_csv("model\tinput_per_mtok\toutput_per_mtok\nm1\t1\t2\n")
    assert errors == [] and rows["m1"].input_per_mtok == 1


def test_csv_reports_every_bad_line_with_its_number():
    text = "model,input_per_mtok,output_per_mtok\nok,1,2\nbad name!,1,2\nm2,abc,2\nok,3,4\nshort\n"
    rows, errors = parse_models_csv(text)
    assert [e.split(":")[0] for e in errors] == ["line 3", "line 4", "line 5", "line 6"]
    assert "appears twice" in errors[2] and "too few columns" in errors[3]


def test_csv_needs_a_proper_header_and_at_least_one_model():
    assert "header needs" in parse_models_csv("name,price\nm,1\n")[1][0]
    assert parse_models_csv("")[1] == ["the CSV is empty"]
    assert "no models" in parse_models_csv("model,input_per_mtok,output_per_mtok\n")[1][0]


def test_exported_csv_imports_back_to_the_same_prices(base):
    rows, errors = parse_models_csv(to_csv(base.cost.models))
    assert errors == [] and rows == base.cost.models


# ---- saved settings -------------------------------------------------------------------------------
def test_with_nothing_saved_the_file_settings_apply(ms, base):
    prices, models, followup, pins = ms.effective()
    assert models == base.routing.models and followup == base.routing.followup_model
    assert pins == base.routing.pin and prices == base.cost.models


def test_imported_models_add_to_the_list_and_can_override_a_file_price(ms):
    n = ms.import_csv("model,input_per_mtok,output_per_mtok\nnew-model,1,2\nqwen3-32b,9,9\n")
    prices = ms.prices()
    assert (
        n == 2
        and prices["new-model"].input_per_mtok == 1
        and prices["qwen3-32b"].output_per_mtok == 9
    )


def test_a_bad_csv_saves_nothing(ms):
    with pytest.raises(SettingsError, match="line 3"):
        ms.import_csv("model,input_per_mtok,output_per_mtok\ngood,1,2\nbad,x,2\n")
    assert ms.saved_prices() == {}


def test_a_decision_can_only_use_a_model_on_the_list(ms):
    with pytest.raises(SettingsError, match="not in the model list"):
        ms.save_roles({"hit": "ghost-model"})
    ms.import_csv("model,input_per_mtok,output_per_mtok\nghost-model,1,2\n")
    ms.save_roles({"hit": "ghost-model", "pin:repo_facts": ""})
    _, models, _, pins = ms.effective()
    assert (
        models.hit == "ghost-model" and "repo_facts" not in pins
    )  # an empty pin clears the file's


def test_unknown_decisions_and_routes_are_refused(ms):
    with pytest.raises(SettingsError, match="unknown decision"):
        ms.save_roles({"nonsense": "qwen3-32b"})
    with pytest.raises(SettingsError, match="not a route"):
        ms.save_roles({"pin:nope": "qwen3-32b"})
    with pytest.raises(SettingsError, match="choose a model for hit"):
        ms.save_roles({"hit": ""})


def test_a_model_in_use_cannot_be_removed_or_replaced_away(ms):
    ms.import_csv("model,input_per_mtok,output_per_mtok\nextra,1,2\n")
    ms.save_roles({"miss": "extra"})
    with pytest.raises(SettingsError, match="in use"):
        ms.delete_model("extra")
    with pytest.raises(SettingsError, match="in use"):
        ms.import_csv("model,input_per_mtok,output_per_mtok\nother,1,2\n", replace=True)
    ms.save_roles({"miss": "claude-sonnet-5-5"})
    ms.delete_model("extra")
    assert "extra" not in ms.saved_prices()


def test_models_from_the_file_cannot_be_deleted(ms):
    with pytest.raises(SettingsError, match="not a saved model"):
        ms.delete_model("qwen3-32b")


def test_replace_drops_saved_models_but_keeps_the_files(ms):
    ms.import_csv("model,input_per_mtok,output_per_mtok\na,1,2\nb,1,2\n")
    ms.import_csv("model,input_per_mtok,output_per_mtok\nc,1,2\n", replace=True)
    assert set(ms.saved_prices()) == {"c"} and "qwen3-32b" in ms.prices()


def test_token_check_needs_a_configured_matching_token():
    assert token_ok("s3cret", "s3cret")
    assert not token_ok("wrong", "s3cret") and not token_ok("", "s3cret")
    assert not token_ok("anything", None) and not token_ok(None, "")  # no token set: editing off


# ---- the hot swap and the page --------------------------------------------------------------------
def test_apply_models_swaps_decisions_prices_and_the_savings_baseline(ms):
    from semcache.chat import ChatService

    chat = ChatService.__new__(ChatService)
    chat.pricing = Pricing({"old": ModelPrice(input_per_mtok=1, output_per_mtok=1)})
    ms.import_csv("model,input_per_mtok,output_per_mtok\nnew-big,10,20\n")
    ms.save_roles({"miss": "new-big"})
    prices, models, followup, pins = ms.effective()
    chat.apply_models(models, pins, followup, prices)
    assert chat.models.miss == "new-big" and chat.baseline_model == "new-big"
    assert chat.pricing.cost("new-big", 1_000_000, 0) == 10 and not chat.pricing.known("old")


def make_client(base, token="letmein"):
    app = FastAPI()
    app.include_router(router)
    store = ModelSettings(FakeValkey(), base)
    applied = []
    chat = SimpleNamespace(
        jev=None, apply_models=lambda *a: applied.append(a),
    )  # fmt: skip
    app.state.model_settings, app.state.chat = store, chat
    app.state.admin_token, app.state.gateway_models = token, {"qwen3-32b"}
    return TestClient(app, follow_redirects=False), store, applied


def test_the_page_shows_decisions_models_and_a_gateway_warning(base):
    client, _, _ = make_client(base)
    html = client.get("/settings").text
    assert "Which model makes each decision" in html and 'name="pin_repo_facts"' in html
    assert "qwen3-32b" in html and "not on the gateway" in html  # claude-* are not in the stub list
    assert "Read-only" not in html


def test_without_an_admin_token_the_page_is_read_only_and_refuses_edits(base):
    client, store, applied = make_client(base, token=None)
    assert "Read-only" in client.get("/settings").text
    r = client.post("/settings/roles", data={"hit": "qwen3-32b", "token": "x"})
    assert r.status_code == 303 and "Editing+is+off" in r.headers["location"]
    assert applied == [] and store.saved_roles() == {}


def test_a_wrong_token_changes_nothing(base):
    client, store, applied = make_client(base)
    r = client.post("/settings/roles", data={"hit": "qwen3-32b", "token": "nope"})
    assert "token+is+not+right" in r.headers["location"] and applied == []
    r = client.post("/settings/models/import", data={"csv_text": "x", "token": ""})
    assert "token+is+not+right" in r.headers["location"] and store.saved_prices() == {}


def test_saving_choices_persists_and_applies_them(base):
    client, store, applied = make_client(base)
    form = {"hit": "qwen3-32b", "classifier": "claude-haiku-4-5", "miss": "claude-sonnet-5-5",
            "followup": "claude-haiku-4-5", "pin_repo_facts": "qwen3-32b", "token": "letmein"}  # fmt: skip
    r = client.post("/settings/roles", data=form)
    assert r.headers["location"].startswith("/settings?ok=") and len(applied) == 1
    assert store.effective()[3]["repo_facts"] == "qwen3-32b"
    assert applied[0][1]["repo_facts"] == "qwen3-32b"  # the pins handed to the chat service


def test_csv_import_by_paste_and_by_file_then_the_new_model_is_selectable(base):
    client, store, applied = make_client(base)
    csv_text = "model,input_per_mtok,output_per_mtok\npasted,1,2\n"
    r = client.post("/settings/models/import", data={"csv_text": csv_text, "token": "letmein"})
    assert "Imported+1+model." in r.headers["location"] and "pasted" in store.saved_prices()
    files = {"csv_file": ("m.csv", b"model,input_per_mtok,output_per_mtok\nfrom-file,$3/M,$4/M\n")}
    r = client.post("/settings/models/import", data={"token": "letmein"}, files=files)
    assert "from-file" in store.saved_prices() and len(applied) == 2
    assert 'value="from-file"' in client.get("/settings").text


def test_a_bad_import_explains_itself_and_changes_nothing(base):
    client, store, applied = make_client(base)
    bad = "model,input_per_mtok,output_per_mtok\nok,1,2\nbad,zzz,2\n"
    r = client.post("/settings/models/import", data={"csv_text": bad, "token": "letmein"})
    assert "Nothing+imported" in r.headers["location"] and "line+3" in r.headers["location"]
    assert store.saved_prices() == {} and applied == []


def test_delete_and_the_csv_download(base):
    client, store, _ = make_client(base)
    store.import_csv("model,input_per_mtok,output_per_mtok\nbye,1,2\n")
    r = client.post("/settings/models/delete", data={"name": "bye", "token": "letmein"})
    assert "Removed+bye" in r.headers["location"] and "bye" not in store.saved_prices()
    out = client.get("/settings/models.csv")
    assert out.headers["content-type"].startswith("text/csv")
    assert out.text.splitlines()[0] == "model,input_per_mtok,output_per_mtok"
    assert CATALOG_KEY not in store.r.h or "bye" not in store.r.h[CATALOG_KEY]


def test_messages_from_the_url_are_escaped(base):
    client, _, _ = make_client(base)
    html = client.get("/settings", params={"err": "<script>alert(1)</script>"}).text
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html
