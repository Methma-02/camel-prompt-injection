# Runs the pilot and writes the results.
#
# How to run (from the camel-prompt-injection folder):
#     uv run python -m pilot.run_pilot --qllm stub
#     uv run --env-file .env python -m pilot.run_pilot --qllm openai:llama31-camel --repeats 5 --out pilot_out_llama_v2
#
# Files written to the --out folder (default pilot_out):
#     results.md  the summary tables
#     slots.json  one row per slot (plan, mode, call, argument), judged over all edits
#     cells.json  one row per edit and slot
#     runs.json   every logged call with its labels and the policy decision, for every run

from __future__ import annotations

import argparse
import dataclasses
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from camel.interpreter.interpreter import MetadataEvalMode
from camel.pipeline_elements.security_policies.banking import banking_no_side_effect_tools
from pilot.oracle import Cell, evaluate_plan, summarise_slots
from pilot.plans import PLANS

READ_ONLY = set(banking_no_side_effect_tools)
CELLS = ("TP", "FP", "FN", "TN")  # plus UNSTABLE, reported separately


def _fmt(v: object) -> str:
    if isinstance(v, list) and len({json.dumps(x, default=str) for x in v}) == 1:
        v = f"{_fmt(v[0])} (x{len(v)})"  # all runs agree: show the value once
    s = json.dumps(v, default=str) if not isinstance(v, str) else v
    s = s.replace("|", "/")
    return s if len(s) <= 60 else s[:57] + "..."


def write_markdown(cells: list[Cell], infos: list[dict], backend: str, repeats: int, path: Path) -> None:
    lines = [
        "# I0 feasibility spike: results",
        "",
        f"- Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- Suite: AgentDojo v1.2 Banking; quarantined LLM: `{backend}`; runs per condition (unedited, and each edit): {repeats}",
        "- Plans are fixed and hand-written; only untrusted file contents are edited.",
        "- Cell = CaMeL label (untrusted/trusted) x oracle (changed/unchanged): "
        "TP untrusted+changed, FP untrusted+unchanged, FN trusted+changed, TN trusted+unchanged.",
        "",
        "Each slot is one argument of one call (or `<occurrence>`: whether the call happens at all), "
        "in one plan and mode. A slot counts as changed if at least one edit changed it in every edited run, "
        "beyond the values seen in the unedited runs. A slot an edit changed in some runs but not others is "
        "UNSTABLE: the change cannot be told apart from model noise, so it is kept out of TP/FP/FN/TN.",
        "",
        "## Totals by mode (slots)",
        "",
        "| Mode | TP | FP | FN | TN | Unstable | Slots |",
        "|---|---|---|---|---|---|---|",
    ]
    slots = summarise_slots(cells)
    for mode in ("NORMAL", "STRICT"):
        c = Counter(x.cell for x in slots if x.mode == mode)
        lines.append(
            f"| {mode} | " + " | ".join(str(c[k]) for k in CELLS) + f" | {c['UNSTABLE']} | {sum(c.values())} |"
        )

    lines += [
        "",
        "## Every slot",
        "",
        "| Plan | Mode | Call | Slot | CaMeL label | Changed by | Unstable under | Cell |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for x in slots:
        lines.append(
            f"| {x.plan} | {x.mode} | {x.tool}#{x.occurrence} | {x.target} | {x.camel_label} | "
            f"{', '.join(x.changed_by) or '-'} | {', '.join(x.unstable_under) or '-'} | **{x.cell}** |"
        )

    lines += [
        "",
        "## Noise: how much repeated runs of the same input differ",
        "",
        "| Plan | Mode | Input | Change rate between runs | Errors |",
        "|---|---|---|---|---|",
    ]
    for info in infos:
        errs = "; ".join(sorted(set(info["control_errors"]))) or "none"
        lines.append(f"| {info['plan']} | {info['mode']} | unedited | {info['control_change_rate']:.2f} | {errs} |")
        for e in info["edits"]:
            errs = "; ".join(sorted({x for x in e["errors"] if x})) or "none"
            lines.append(
                f"| {info['plan']} | {info['mode']} | {e['edit']} | {e['change_rate_between_edited_runs']:.2f} | {errs} |"
            )

    lines += [
        "",
        "## Every edit, slot by slot",
        "",
        "| Plan | Edit (type) | Mode | Call | Argument | CaMeL label | Unedited runs | Edited runs | Verdict | Cell |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for x in cells:
        lines.append(
            f"| {x.plan} | {x.edit} ({x.edit_type}) | {x.mode} | {x.tool}#{x.occurrence} | {x.target} | "
            f"{x.camel_label} | {_fmt(x.control_values)} | {_fmt(x.edited_values)} | {x.verdict} | **{x.cell}** |"
        )

    lines += ["", "## Plans and what the code analysis predicts", ""]
    for p in PLANS:
        lines.append(f"- **{p.id}** ({p.based_on}): {p.description} Expected: {p.expected}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the counterfactual label oracle pilot on the Banking suite.")
    ap.add_argument(
        "--qllm",
        default="stub",
        help="'stub', or a model name passed to CaMeL's quarantined LLM, e.g. openai:llama31-camel (default: stub)",
    )
    ap.add_argument(
        "--repeats",
        type=int,
        default=None,
        help="runs per condition (unedited, and each edit) (default: 2 for stub, 3 otherwise)",
    )
    ap.add_argument("--plans", nargs="*", default=None, help="plan ids to run (default: all)")
    ap.add_argument("--out", default="pilot_out")
    args = ap.parse_args()

    repeats = args.repeats or (2 if args.qllm == "stub" else 3)
    plans = [p for p in PLANS if args.plans is None or p.id in args.plans]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    cells: list[Cell] = []
    infos: list[dict] = []
    for plan in plans:
        for mode in (MetadataEvalMode.NORMAL, MetadataEvalMode.STRICT):
            print(f"running {plan.id} [{mode}] ...", flush=True)
            c, info = evaluate_plan(plan, mode, args.qllm, repeats, READ_ONLY)
            cells += c
            infos.append(info)

    (out / "cells.json").write_text(
        json.dumps([dataclasses.asdict(c) for c in cells], indent=2, default=str), encoding="utf-8"
    )
    (out / "runs.json").write_text(json.dumps(infos, indent=2, default=str), encoding="utf-8")
    write_markdown(cells, infos, args.qllm, repeats, out / "results.md")

    slots = summarise_slots(cells)
    (out / "slots.json").write_text(json.dumps([dataclasses.asdict(s) for s in slots], indent=2), encoding="utf-8")
    for mode in ("NORMAL", "STRICT"):
        c = Counter(x.cell for x in slots if x.mode == mode)
        print(f"{mode}: " + "  ".join(f"{k}={c[k]}" for k in CELLS) + f"  UNSTABLE={c['UNSTABLE']}")
    print(f"wrote {out / 'results.md'}")


if __name__ == "__main__":
    main()
