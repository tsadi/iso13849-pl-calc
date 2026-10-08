"""Command line: evaluate a safety function described in a JSON file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import core


def _component_mttfd(comp: dict, nop: float | None) -> float:
    if "mttfd_years" in comp:
        return float(comp["mttfd_years"])
    if "b10d" in comp:
        if nop is None:
            raise core.InputError(f"component {comp.get('name')!r} uses B10D but no 'operation' block is given")
        return core.mttfd_from_b10d(float(comp["b10d"]), nop)
    raise core.InputError(f"component {comp.get('name')!r} needs mttfd_years or b10d")


def evaluate_subsystem(sub: dict, nop: float | None) -> dict:
    channels = sub.get("channels") or []
    if not channels:
        raise core.InputError(f"subsystem {sub.get('name')!r} has no channels")
    ch_mttfd = []
    dc_pairs = []
    rows = []
    for ci, channel in enumerate(channels, start=1):
        vals = []
        for comp in channel:
            m = _component_mttfd(comp, nop)
            vals.append(m)
            dc_pairs.append((float(comp.get("dc", 0.0)), m))
            row = {"channel": ci, "name": comp.get("name", "?"), "mttfd": m, "dc": float(comp.get("dc", 0.0))}
            if "b10d" in comp and nop:
                row["t10d"] = core.t10d_years(float(comp["b10d"]), nop)
            rows.append(row)
        ch_mttfd.append(core.mttfd_series(vals))

    if len(ch_mttfd) == 1:
        mttfd = ch_mttfd[0]
    elif len(ch_mttfd) == 2:
        mttfd = core.mttfd_symmetrise(*ch_mttfd)
    else:
        raise core.InputError("the simplified method supports one or two channels")

    dcavg = core.dc_avg(dc_pairs)
    res = core.pl_simplified(str(sub["category"]), mttfd, dcavg, sub.get("ccf_score"))
    return {"name": sub.get("name", "subsystem"), "rows": rows, "channel_mttfd": ch_mttfd, "result": res}


def evaluate(spec: dict) -> dict:
    op = spec.get("operation")
    nop = core.nop_per_year(op["days_per_year"], op["hours_per_day"], op["cycle_time_s"]) if op else None

    if "plr" in spec:
        plr = str(spec["plr"]).lower()
    elif "risk_graph" in spec:
        rg = spec["risk_graph"]
        plr = core.plr_from_risk_graph(rg["s"], rg["f"], rg["p"])
    else:
        raise core.InputError("give either 'plr' or 'risk_graph' {s,f,p}")

    subs = [evaluate_subsystem(s, nop) for s in spec["subsystems"]]
    pls = [s["result"].pl for s in subs]
    if all(pls):
        overall = core.combine_by_count(pls)
    else:
        overall = None
    pfhd_total = None
    if all("pfhd" in s for s in spec["subsystems"]):
        pfhd_total, pfhd_pl = core.combine_by_pfhd(float(s["pfhd"]) for s in spec["subsystems"])
    return {"name": spec.get("name", "safety function"), "plr": plr, "nop": nop,
            "subsystems": subs, "overall": overall, "pfhd_total": pfhd_total}


def render_markdown(r: dict) -> str:
    out = [f"# {r['name']}", ""]
    out.append(f"Required PL (PLr): **{r['plr']}**")
    if r["nop"]:
        out.append(f"Operations per year (nop): {r['nop']:,.0f}")
    out.append("")
    for s in r["subsystems"]:
        res = s["result"]
        out.append(f"## {s['name']}")
        out.append("")
        out.append("| Ch | Component | MTTFd (y) | DC | T10D (y) |")
        out.append("|---|---|---|---|---|")
        for row in s["rows"]:
            t10 = f"{row['t10d']:.1f}" if "t10d" in row else "-"
            out.append(f"| {row['channel']} | {row['name']} | {row['mttfd']:.1f} | {row['dc']:.0%} | {t10} |")
        out.append("")
        dc_txt = f"{res.dc_avg:.1%}" if res.dc_avg is not None else "n/a"
        out.append(f"Category {res.category} · MTTFd {res.mttfd_years:.1f} y ({res.mttfd_band}) · "
                   f"DCavg {dc_txt} ({res.dc_band}) · CCF {res.ccf_score if res.ccf_score is not None else 'n/a'}")
        out.append(f"Subsystem PL: **{res.pl or 'not achieved'}**")
        for n in res.notes:
            out.append(f"- {n}")
        out.append("")
    verdict = "meets" if core.meets(r["overall"], r["plr"]) else "does NOT meet"
    out.append("## Safety function")
    out.append("")
    out.append(f"Combined PL (by count): **{r['overall'] or 'not achieved'}**, which {verdict} PLr {r['plr']}.")
    if r["pfhd_total"] is not None:
        out.append(f"Sum of subsystem PFHd: {r['pfhd_total']:.2e} /h → PL {core.pl_from_pfhd(r['pfhd_total']) or 'below a'}.")
    out.append("")
    out.append("_Simplified procedure. Verify with SISTEMA or an equivalent validated tool; "
               "systematic failures, software and validation (ISO 13849-2) are not covered._")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="iso13849-pl", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    ev = sub.add_parser("evaluate", help="evaluate a safety function from a JSON spec")
    ev.add_argument("spec", type=Path)
    ev.add_argument("-o", "--out", type=Path, help="write the markdown report here")

    rg = sub.add_parser("plr", help="required PL from the risk graph")
    rg.add_argument("--s", type=int, required=True)
    rg.add_argument("--f", type=int, required=True)
    rg.add_argument("--p", type=int, required=True)

    b10 = sub.add_parser("mttfd", help="MTTFd and T10D from B10D")
    b10.add_argument("--b10d", type=float, required=True)
    b10.add_argument("--days", type=float, required=True)
    b10.add_argument("--hours", type=float, required=True)
    b10.add_argument("--cycle", type=float, required=True, help="cycle time in seconds")

    args = ap.parse_args(argv)
    try:
        if args.cmd == "plr":
            print(core.plr_from_risk_graph(args.s, args.f, args.p))
        elif args.cmd == "mttfd":
            nop = core.nop_per_year(args.days, args.hours, args.cycle)
            print(f"nop={nop:,.0f}/y  MTTFd={core.mttfd_from_b10d(args.b10d, nop):.1f} y  "
                  f"T10D={core.t10d_years(args.b10d, nop):.1f} y")
        else:
            report = render_markdown(evaluate(json.loads(args.spec.read_text())))
            if args.out:
                args.out.write_text(report)
            print(report)
    except core.InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
