"""Figures for the report, drawn from the eval result files (no numbers typed by hand).

Run: uv run python docs/report/make_figures.py   → docs/report/img/fig-*.png
"""

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RES, OUT = ROOT / "evals" / "results", ROOT / "docs" / "report" / "img"
OUT.mkdir(parents=True, exist_ok=True)

INK, MUTED, ACCENT = "#1F1D1A", "#7A746C", "#E8562A"
BLUE, GREEN, LINE = "#466A92", "#2E7D4F", "#E6E1D9"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": LINE, "axes.labelcolor": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.dpi": 160, "savefig.bbox": "tight"})


def load(name: str) -> dict:
    return json.loads((RES / f"{name}.json").read_text())


def save(fig, name: str) -> None:
    fig.savefig(OUT / name)
    plt.close(fig)
    print("wrote", OUT / name)


def fig_intervals():
    """Rate metrics with 95% Wilson intervals: how much the small sets can claim."""
    rows = load("intervals")["intervals"]
    fig, ax = plt.subplots(figsize=(7.5, 0.42 * len(rows) + 0.8))
    for i, r in enumerate(reversed(rows)):
        lo, hi = r["ci95"]
        lower_is_better = "false alarm" in r["metric"] or "attack" in r["metric"]
        c = BLUE if lower_is_better else GREEN
        ax.plot([lo, hi], [i, i], color=c, lw=3, alpha=.35, solid_capstyle="round")
        ax.plot(r["value"], i, "o", color=c, ms=7)
        ax.text(1.03, i, f"{r['k']}/{r['n']}", va="center", fontsize=8, color=MUTED,
                transform=ax.get_yaxis_transform())
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{r['component']}: {r['metric']}" for r in reversed(rows)])
    ax.set_xlim(-0.02, 1.02)
    ax.set_xlabel("value with 95% Wilson interval (green: higher is better, blue: lower is better)")
    ax.grid(axis="x", color=LINE, lw=.6)
    save(fig, "fig-intervals.png")


def fig_baselines():
    """Each model component against its simple baseline."""
    c3, c5, c4 = load("c3_nutrition")["metrics"], load("c5_daytype")["metrics"], load(
        "c4_sources")["metrics"]
    c4v1 = json.loads((RES / "v1" / "c4_sources.json").read_text())["metrics"]
    base = load("intervals")["c5_majority_baseline"]
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.2))
    ax = axes[0]
    labels, model, mean_b = ["NutriBench", "Ukrainian"], [c3["nb_mae_kcal"], c3["ua_mae_kcal"]], [
        c3["nb_baseline_mae_kcal"], c3["ua_baseline_mae_kcal"]]
    x = range(2)
    ax.bar([i - .18 for i in x], mean_b, .36, color=LINE, label="predict the mean")
    ax.bar([i + .18 for i in x], model, .36, color=ACCENT, label="C3 (LLM)")
    for i in x:
        ax.text(i + .18, model[i] + 4, f"{model[i]:.0f}", ha="center", fontsize=8)
        ax.text(i - .18, mean_b[i] + 4, f"{mean_b[i]:.0f}", ha="center", fontsize=8, color=MUTED)
    ax.set_xticks(list(x), labels)
    ax.set_title("C3 nutrition: kcal error (lower is better)", fontsize=9)
    ax.legend(frameon=False, fontsize=8)
    ax = axes[1]
    names = ["majority\nclass", "watch-only\nrule", "C5 (LLM)"]
    vals = [base["kappa"], c5["baseline_kappa"], c5["kappa"]]
    ax.bar(names, vals, color=[LINE, LINE, ACCENT])
    for i, v in enumerate(vals):
        ax.text(i, v + .02, f"{v:.2f}", ha="center", fontsize=8)
    ax.set_ylim(0, 1)
    ax.set_title("C5 day type: Cohen's κ (higher is better)", fontsize=9)
    ax = axes[2]
    names = ["recall@1", "recall@5", "MRR"]
    v1 = [c4v1["retrieval_recall_at_1"], c4v1["retrieval_recall_at_5"], c4v1["mrr"]]
    v2 = [c4["retrieval_recall_at_1"], c4["retrieval_recall_at_5"], c4["mrr"]]
    ax.bar([i - .18 for i in range(3)], v1, .36, color=LINE, label="2,800-char chunks")
    ax.bar([i + .18 for i in range(3)], v2, .36, color=ACCENT, label="1,400-char chunks")
    ax.set_xticks(range(3), names)
    ax.set_ylim(0, 1)
    ax.set_title("C4 search (higher is better)", fontsize=9)
    ax.legend(frameon=False, fontsize=7, loc="upper left", bbox_to_anchor=(0, 1.0))
    ax.set_ylim(0, 1.15)
    fig.tight_layout()
    save(fig, "fig-baselines.png")


def fig_confusion():
    """C5 confusion matrix: where the two errors are, and that they are one level off."""
    conf = load("c5_daytype")["confusion"]
    classes = ["recover", "easy", "normal", "push"]
    m = [[conf[g].get(p, 0) for p in classes] for g in classes]
    fig, ax = plt.subplots(figsize=(3.8, 3.4))
    ax.imshow(m, cmap="Oranges")
    for i in range(4):
        for j in range(4):
            ax.text(j, i, m[i][j], ha="center", va="center",
                    color="white" if m[i][j] > 6 else INK, fontsize=10)
    ax.set_xticks(range(4), classes)
    ax.set_yticks(range(4), classes)
    ax.set_xlabel("predicted")
    ax.set_ylabel("gold label")
    ax.set_title("C5 day type, 30 scenarios", fontsize=9)
    save(fig, "fig-c5-confusion.png")


def fig_c3_scatter():
    """C3 predicted vs reference kcal, with the ±20% band."""
    cases = load("c3_nutrition").get("cases")
    if not cases:
        print("skip fig-c3-scatter (run evals.run_c3 first)")
        return
    fig, ax = plt.subplots(figsize=(4.4, 4.2))
    top = max(max(c["gold_kcal"], c["pred_kcal"]) for c in cases) * 1.05
    ax.fill_between([0, top], [0, top * .8], [0, top * 1.2], color=GREEN, alpha=.08,
                    label="within ±20%")
    ax.plot([0, top], [0, top], color=MUTED, lw=.8)
    for src, color, lab in (("nutribench-v2", ACCENT, "NutriBench"),
                            ("ua-reference-table", BLUE, "Ukrainian")):
        pts = [c for c in cases if c["source"] == src]
        lab = f"{lab} ({len(pts)})"
        ax.scatter([c["gold_kcal"] for c in pts], [c["pred_kcal"] for c in pts], s=16, color=color,
                   label=lab, alpha=.85)
    ax.set_xlim(0, top)
    ax.set_ylim(0, top)
    ax.set_xlabel("reference kcal")
    ax.set_ylabel("C3 estimate, kcal")
    ax.set_title("C3: estimate vs reference per meal", fontsize=9)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    save(fig, "fig-c3-scatter.png")


def fig_iterations():
    """What each round of fixes changed, for the components that were re-run."""
    v1 = {n: json.loads((RES / "v1" / f"{n}.json").read_text())["metrics"]
          for n in ("c6_planner", "c8_reply", "c4_sources")}
    now = {n: load(n)["metrics"] for n in ("c6_planner", "c8_reply", "c4_sources", "e2e_agent")}
    rows = [("C6 valid first try", v1["c6_planner"]["valid_first_try"],
             now["c6_planner"]["valid_first_try"]),
            ("C6 judge (÷5)", v1["c6_planner"]["judge_mean"] / 5,
             now["c6_planner"]["judge_mean"] / 5),
            ("C8 correct", v1["c8_reply"]["correct"], now["c8_reply"]["correct"]),
            ("C4 recall@5", v1["c4_sources"]["retrieval_recall_at_5"],
             now["c4_sources"]["retrieval_recall_at_5"]),
            ("E2E cases (run 1 → 2)", 11 / 12, now["e2e_agent"]["case_pass_rate"])]
    fig, ax = plt.subplots(figsize=(6.5, 2.8))
    for i, (_name, a, b) in enumerate(reversed(rows)):
        ax.annotate("", xy=(b, i), xytext=(a, i),
                    arrowprops={"arrowstyle": "->", "color": ACCENT, "lw": 1.6})
        ax.plot(a, i, "o", color=LINE, ms=7)
        ax.plot(b, i, "o", color=ACCENT, ms=7)
        ax.text(b + .01, i + .18, f"{a:.2f} → {b:.2f}", fontsize=8, color=MUTED)
    ax.set_yticks(range(len(rows)), [r[0] for r in reversed(rows)])
    ax.set_xlim(.7, 1.06)
    ax.set_title("Before → after the fixes found by the evals", fontsize=9)
    ax.grid(axis="x", color=LINE, lw=.6)
    save(fig, "fig-iterations.png")


def fig_patterns():
    """Simulation that chose the patterns threshold: false patterns vs real effects found."""
    from app import patterns
    ts = [0, 1.5, 2.0, 2.5, 3.0, 3.5]
    false, found = [], []
    for t in ts:
        patterns.MIN_T = t
        rng, hits = random.Random(7), 0
        for _ in range(150):
            days = {date(2026, 1, 1) + timedelta(days=i): (
                {"late_meal"} if rng.random() < .15 else set()) for i in range(90)}
            w = {d + timedelta(days=1): {"hrv": rng.gauss(60, 8), "resting_hr": rng.gauss(50, 3),
                                         "sleep_h": rng.gauss(7, .8)} for d in days}
            hits += bool(patterns.compare(days, w))
        rng, det = random.Random(3), 0
        for _ in range(100):
            days = {date(2026, 1, 1) + timedelta(days=i): (
                {"alcohol"} if rng.random() < .12 else set()) for i in range(90)}
            w = {d + timedelta(days=1): {"hrv": rng.gauss(54 if "alcohol" in days[d] else 60, 8),
                                         "resting_hr": rng.gauss(50, 3),
                                         "sleep_h": rng.gauss(7, .8)} for d in days}
            det += any(p["tag"] == "alcohol" and p["metric"] == "hrv"
                       for p in patterns.compare(days, w))
        false.append(hits / 150)
        found.append(det / 100)
    patterns.MIN_T = 2.5
    fig, ax = plt.subplots(figsize=(5.4, 3.2))
    ax.plot(ts, false, "o-", color=BLUE, label="false pattern on random data")
    ax.plot(ts, found, "o-", color=GREEN, label="real −10% HRV after alcohol found")
    ax.axvline(2.5, color=ACCENT, ls="--", lw=1)
    ax.text(2.55, .9, "chosen: t ≥ 2.5", color=ACCENT, fontsize=8)
    ax.set_xlabel("minimum Welch t (0 = the old rule)")
    ax.set_ylabel("share of simulated 90-day logs")
    ax.set_ylim(0, 1)
    ax.legend(frameon=False, fontsize=8)
    ax.set_title("Patterns: fewer false claims vs fewer real findings", fontsize=9)
    save(fig, "fig-patterns.png")


if __name__ == "__main__":
    fig_intervals()
    fig_baselines()
    fig_confusion()
    fig_c3_scatter()
    fig_iterations()
    fig_patterns()
