"""C10 code part: catalogue aliases, unit conversions, number and range parsing, flags."""

import pytest

from app import lab_catalog as cat
from app.pipeline import labs
from app.pipeline.labs import LabSheet, PrintedRow


@pytest.mark.parametrize("printed,key", [
    ("Ferritin", "ferritin"), ("Феритин", "ferritin"), ("Ферритин", "ferritin"),
    ("Гемоглобін (HGB)", "hgb"), ("HGB", "hgb"), ("Гемоглобин", "hgb"),
    ("Вітамін D (25-OH)", "vitamin_d"), ("25-OH Vitamin D", "vitamin_d"),
    ("Вітамін В12", "b12"), ("ТТГ", "tsh"), ("Тиреотропный гормон", "tsh"),
    ("Холестерин ЛПНЩ", "ldl"), ("Холестерин загальний", "chol_total"), ("ШОЕ", "esr"),
    ("Лейкоцити (WBC)", "wbc"), ("Тромбоциты", "plt"), ("Glucose", "glucose"),
    ("ШОЕ (ESR)", "esr"), ("ЛПНЩ (LDL)", "ldl"), ("ТТГ (TSH)", "tsh"), ("ЛПВЩ (HDL)", "hdl"),
])
def test_aliases(printed, key):
    assert cat.find(printed) == key


def test_unknown_marker():
    assert cat.find("Прокальцитонін") is None


@pytest.mark.parametrize("marker,unit,value,expected", [
    ("vitamin_d", "ng/mL", 30, 74.88), ("testosterone", "ng/dL", 576.8, 20.0),
    ("glucose", "mg/dL", 90, 5.0), ("b12", "pg/mL", 400, 295.2), ("hgb", "g/dL", 14.2, 142),
    ("ferritin", "ng/mL", 18, 18), ("ferritin", "мкг/л", 18, 18), ("hgb", "г/л", 142, 142),
])
def test_conversions(marker, unit, value, expected):
    assert value * cat.factor(marker, unit) == pytest.approx(expected, rel=1e-3)


@pytest.mark.parametrize("marker,unit,canon_value,printed_value", [
    ("vitamin_d", "ng/mL", 74.88, 30), ("testosterone", "ng/dL", 20.0, 576.8),
    ("glucose", "mg/dL", 5.0, 90), ("b12", "pg/mL", 295.2, 400), ("hgb", "g/dL", 142, 14.2),
])
def test_conversions_back(marker, unit, canon_value, printed_value):
    assert canon_value / cat.factor(marker, unit) == pytest.approx(printed_value, rel=1e-3)


@pytest.mark.parametrize("s,out", [
    ("12,4", (12.4, None, None)), ("12.4*", (12.4, None, None)), ("<0.5", (0.5, "<", None)),
    (">1000", (1000.0, ">", None)), ("негативний", (None, None, "негативний")),
    ("5,6 ↑", (5.6, None, None)),
])
def test_numbers(s, out):
    assert labs.parse_number(s) == out


@pytest.mark.parametrize("s,out", [
    ("30 - 100", (30, 100)), ("30–100", (30, 100)), ("4,0 - 9,0", (4.0, 9.0)),
    ("до 15", (None, 15)), ("< 5.2", (None, 5.2)), ("> 1.0", (1.0, None)),
    ("від 2", (2, None)), ("", (None, None)),
])
def test_ranges(s, out):
    assert labs.parse_range(s) == out


def _sheet(*rows):
    return LabSheet(lab="X", taken_on="2026-09-12", rows=[PrintedRow(
        name_as_printed=n, value_as_printed=v, unit_as_printed=u, ref_as_printed=r)
        for n, v, u, r in rows])


def test_printed_range_beats_default():
    r = labs.normalise(_sheet(("Феритин", "25", "нг/мл", "20 - 250")))[0]
    assert (r["marker"], r["value"], r["unit"], r["ref_low"], r["flag"]) == (
        "ferritin", 25, "µg/L", 20, "in")  # the default 30–400 would say low


def test_default_range_when_none_printed():
    r = labs.normalise(_sheet(("Ferritin", "18", "ng/mL", "")))[0]
    assert (r["ref_low"], r["ref_high"], r["flag"]) == (30, 400, "low")


def test_conversion_converts_range_too():
    r = labs.normalise(_sheet(("Vitamin D", "20", "ng/mL", "30 - 100")))[0]
    assert r["unit"] == "nmol/L" and r["value"] == pytest.approx(49.92)
    assert r["ref_low"] == pytest.approx(74.88) and r["flag"] == "low"


def test_qualifier_flags():
    rows = labs.normalise(_sheet(("CRP", "<0.5", "mg/L", "< 5"), ("Прокальцитонін", "0,03",
                                                                  "нг/мл", "< 0,05")))
    assert (rows[0]["qualifier"], rows[0]["flag"]) == ("<", "in")
    assert rows[1]["marker"] is None and rows[1]["flag"] == "in"


def test_dates():
    assert str(labs.parse_date("12.09.2026")) == "2026-09-12"
    assert str(labs.parse_date("2026-09-12")) == "2026-09-12"
    assert labs.parse_date("31.02.2026") is None


def test_pdf_without_text_asks_for_photo():
    with pytest.raises(labs.FileError, match="scan"):
        labs.pdf_text(_blank_pdf())


def _blank_pdf() -> bytes:
    import io

    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()
