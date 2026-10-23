"""Run the I0 feasibility spike and write the results.

Examples (from the repository root):

    uv run python -m pilot.run_pilot --qllm stub
    uv run --env-file .env python -m pilot.run_pilot --qllm openai:llama31-camel --repeats 3 --out pilot_out_llama

Outputs in --out (default pilot_out/):
    slots.json    one row per (plan, mode, call, argument) slot, judged over all edits
    cells.json    one row per (plan, edit, mode, call, argument) with its TP/FP/FN/TN cell
    runs.json     every logged call, its labels and the policy decision, per run
    results.md    the summary tables used in the progress evidence
"""

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
CELLS = ("TP", "FP", "FN", "TN")


def _fmt(v: object) -> str:
    s = json.dumps(v) if not isinstance(v, str) else v
    return s if len(s) <= 40 else s[:37] + "..."


def write_markdown(cells: list[Cell], infos: list[dict], backend: str, repeats: int, path: Path) -> None:
    lines = [
        "# I0 feasibility spike: results",
        "",
        f"- Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- Suite: AgentDojo v1.2 Banking; quarantined LLM: `{backend}`; control replays per plan and mode: {repeats}",
        "- Plans are fixed and hand-written; only untrusted file contents are edited.",
        "- Cell = CaMeL label (untrusted/trusted) x oracle (changed/unchanged): "
        "TP untrusted+changed, FP untrusted+unchanged, FN trusted+changed, TN trusted+unchanged.",
        "",
        "Each slot is one argument of one call (or `<occurrence>`: whether the call happens at all), "
        "in one plan and mode. A slot counts as changed if any edit changed it beyond the control-replay noise.",
        "",
        "## Totals by mode (slots)",
        "",
        "| Mode | TP | FP | FN | TN | Slots |",
        "|---|---|---|---|---|---|",
    ]
    slots = summarise_slots(cells)
    for mode in ("NORMAL", "STRICT"):
        c = Counter(x.cell for x in slots if x.mode == mode)
        lines.append(f"| {mode} | " + " | ".join(str(c[k]) for k in CELLS) + f" | {sum(c.values())} |")

    lines += [
        "",
        "## Every slot",
        "",
        "| Plan | Mode | Call | Slot | CaMeL label | Changed by | Cell |",
        "|---|---|---|---|---|---|---|",
    ]
    for x in slots:
        lines.append(
            f"| {x.plan} | {x.mode} | {x.tool}#{x.occurrence} | {x.target} | {x.camel_label} | "
            f"{', '.join(x.changed_by) or '-'} | **{x.cell}** |"
        )

    lines += [
        "",
        "## Control replays (noise)",
        "",
        "| Plan | Mode | Change rate between unedited runs | Errors |",
        "|---|---|---|---|",
    ]
    for info in infos:
        errs = "; ".join(sorted(set(info["control_errors"]))) or "none"
        lines.append(f"| {info['plan']} | {info['mode']} | {info['control_change_rate']:.2f} | {errs} |")

    lines += [
        "",
        "## Every edit, slot by slot",
        "",
        "| Plan | Edit (type) | Mode | Call | Argument | CaMeL label | Before | After | Changed | Cell |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for x in cells:
        lines.append(
            f"| {x.plan} | {x.edit} ({x.edit_type}) | {x.mode} | {x.tool}#{x.occurrence} | {x.target} | "
            f"{x.camel_label} | {_fmt(x.baseline_value)} | {_fmt(x.edited_value)} | {'yes' if x.changed else 'no'} | **{x.cell}** |"
        )

    lines += ["", "## Plans and what the code analysis predicts", ""]
    for p in PLANS:
        lines.append(f"- **{p.id}** ({p.based_on}): {p.description} Expected: {p.expected}")

    edit_errors = [(i["plan"], i["mode"], e["edit"], e["error"]) for i in infos for e in i["edits"] if e["error"]]
    if edit_errors:
        lines += ["", "## Runs that ended in an error", ""]
        lines += [f"- {p} / {m} / {e}: `{err}`" for p, m, e, err in edit_errors]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--qllm",
        default="stub",
        help="'stub', or a model name passed to CaMeL's quarantined LLM, e.g. openai:llama31-camel (default: stub)",
    )
    ap.add_argument(
        "--repeats", type=int, default=None, help="control replays per plan and mode (default: 2 for stub, 3 otherwise)"
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
        print(f"{mode}: " + "  ".join(f"{k}={c[k]}" for k in CELLS))
    print(f"wrote {out / 'results.md'}")


if __name__ == "__main__":
    main()
