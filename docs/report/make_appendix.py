"""Writes docs/report/appendix-prompts-and-tools.md from the code: every agent tool with its
parameters, every structured-output schema, and every system prompt, so the appendix can't
drift from what runs.

Run: uv run python docs/report/make_appendix.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app import agent, sources  # noqa: E402
from app.pipeline import daytype, extract, interview, nutrition, planner, safety  # noqa: E402

PROMPTS = [("coach", "Coach agent (C1 tool routing + C8 answers)", "app/agent.py"),
           ("c7_safety", "C7 Safety gate", "app/pipeline/safety.py"),
           ("c2_extract", "C2 Log extractor", "app/pipeline/extract.py"),
           ("c3_nutrition", "C3 Nutrition estimator", "app/pipeline/nutrition.py"),
           ("c5_daytype", "C5 Day type", "app/pipeline/daytype.py"),
           ("c6_planner", "C6 Workout planner", "app/pipeline/planner.py"),
           ("c4_ingest", "C4 Facts from files", "app/sources.py"),
           ("c0_interview", "C0 Setup interviewer", "app/pipeline/interview.py")]
SCHEMAS = [("C7", safety, "Safety"), ("C2", extract, "Extraction"),
           ("C3", nutrition, "Nutrition"), ("C5", daytype, "Assessment"),
           ("C6", planner, "Workout"), ("C4", sources, "FileFacts"),
           ("C0", interview, "InterviewTurn")]


def params_table(fn: dict) -> str:
    props, req = fn["parameters"].get("properties", {}), fn["parameters"].get("required", [])
    if not props:
        return "_no parameters_\n"
    rows = ["| Parameter | Type | Required | Description |", "|---|---|---|---|"]
    for name, p in props.items():
        t = p.get("type", "")
        if t == "array":
            t = f"array of {p.get('items', {}).get('type', 'object')}"
        if "enum" in p:
            t += " (" + ", ".join(map(str, p["enum"])) + ")"
        desc = (p.get("description") or "").replace("|", "\\|").replace("\n", " ")
        rows.append(f"| `{name}` | {t} | {'yes' if name in req else 'no'} | {desc} |")
    return "\n".join(rows) + "\n"


def main():
    out = ["# Appendix: tools, schemas and system prompts", "",
           "Generated from the code by `docs/report/make_appendix.py`; do not edit by hand.", ""]
    out += ["## 1. The coach agent's tools", "",
            "The coach (Gemini 3.8 Flash) sees these tools as OpenAI-style function definitions. "
            "**Write** tools change data and are recorded with an Undo recipe; nothing writes to "
            "intervals.icu: sending a workout to the watch is a button, not a tool.", ""]
    for t in agent.TOOLS:
        fn = t["function"]
        kind = "write" if fn["name"] in agent.WRITE_TOOLS else "read"
        out += [f"### `{fn['name']}` ({kind})", "", fn["description"], "", params_table(fn)]
    out += ["## 2. Structured outputs", "",
            "Every component returns JSON validated against a Pydantic model (one retry on invalid "
            "output). JSON Schemas of the models:", ""]
    for comp, mod, cls in SCHEMAS:
        model = getattr(mod, cls, None)
        if model is None:
            continue
        schema = json.dumps(model.model_json_schema(), ensure_ascii=False, indent=1)
        out += [f"<details><summary>{comp}: <code>{cls}</code></summary>", "", "```json", schema,
                "```", "", "</details>", ""]
    out += ["## 3. System prompts", "",
            "One Markdown file per component in `app/prompts/`. The data goes in the user message "
            "as JSON; the prompt holds only instructions.", ""]
    for name, title, where in PROMPTS:
        text = (ROOT / "app" / "prompts" / f"{name}.md").read_text().strip()
        out += [f"### {title}", "", f"`app/prompts/{name}.md`, used in `{where}`.", "",
                "````markdown", text, "````", ""]
    path = ROOT / "docs" / "report" / "appendix-prompts-and-tools.md"
    path.write_text("\n".join(out))
    print("wrote", path)


if __name__ == "__main__":
    main()
