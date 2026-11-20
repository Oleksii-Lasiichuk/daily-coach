"""v6: day digest robustness, calorie targets by sex, one Save in Settings."""

from datetime import date

from app import history, nutrition_stats, store
from tests.conftest import login


def test_digest_reads_kcal_from_totals_when_top_level_is_missing():
    d = {"logs": [{"kind": "meal", "data": {"description": "pasta",
                                            "nutrition": {"totals": {"kcal": 650}}}}]}
    assert "650 kcal" in history.digest(date(2026, 11, 14), d)
    assert history.digest(date(2026, 11, 14), {"logs": [{"kind": "meal", "data": {
        "description": "?", "nutrition": {}}}]})  # no kcal anywhere: no crash


def test_targets_use_sex_and_midpoint_when_unknown(users):
    u = users()
    for k, v in {"weight_kg": "70", "height_cm": "175", "birth_year": "1995"}.items():
        store.set_profile_field(u.id, k, v, "user")
    unknown = nutrition_stats.targets(u.id, "normal")["kcal"]
    store.set_profile_field(u.id, "sex", "F", "user")
    female = nutrition_stats.targets(u.id, "normal")["kcal"]
    store.set_profile_field(u.id, "sex", "M", "user")
    male = nutrition_stats.targets(u.id, "normal")["kcal"]
    assert female < unknown < male


def test_settings_you_saves_everything_in_one_post(client, users):
    u = users()
    login(client, u)
    r = client.post("/settings/you", data={"weight_kg": "71", "sex": "F", "lang": "uk",
                                           "time_zone": "Europe/Kyiv", "city": "",
                                           "plan_source": ""}, follow_redirects=False)
    assert r.status_code == 303
    prof = store.get_profile(u.id)
    assert prof["weight_kg"]["value"] == "71" and prof["sex"]["value"] == "F"
    assert store.user_lang(u.id) == "uk"
