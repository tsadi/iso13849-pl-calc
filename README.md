# iso13849-pl-calc

Performance Level (PL) calculator for machine safety functions, following the ISO 13849-1 simplified procedure. It is the hand calculation a safety engineer does at concept and design review, written down so it can be checked, versioned and rerun when a component changes.

You describe a safety function in JSON (risk graph, operating profile, and the input / logic / output subsystems with their components), and it returns:

- PLr from the risk graph (S, F, P)
- MTTFd from B10D for wear parts, plus T10D (replace-before interval)
- channel MTTFd for parts in series, and the two-channel symmetrisation
- DCavg across the subsystem
- the PL each subsystem reaches for its category, MTTFd band and DCavg band
- the combined PL of the safety function, by subsystem count or by summing PFHd
- a markdown report you can drop into a design review

## Example

```
pip install -e .
iso13849-pl evaluate examples/cobot_cell_estop.json
```

```
# Cobot cell: door interlock stops robot motion (STO)

Required PL (PLr): **d**
Operations per year (nop): 23,040

## Input: two interlock switches
| Ch | Component | MTTFd (y) | DC | T10D (y) |
| 1 | Interlock switch A | 868.1 | 99% | 86.8 |
...
Category 3 · MTTFd 100.0 y (high) · DCavg 99.0% (high) · CCF 70
Subsystem PL: **d**
- MTTFd capped at 100 years for category 3.
- DCavg band 'high' read as 'medium' for category 3.
...
Combined PL (by count): **d**, which meets PLr d.
```

Quick calculations without a file:

```
iso13849-pl plr --s 2 --f 1 --p 2          # -> d
iso13849-pl mttfd --b10d 2000000 --days 240 --hours 16 --cycle 600
```

## Input format

```json
{
  "name": "Safety function name",
  "risk_graph": {"s": 2, "f": 2, "p": 1},        // or "plr": "d"
  "operation": {"days_per_year": 240, "hours_per_day": 16, "cycle_time_s": 600},
  "subsystems": [
    {
      "name": "Input",
      "category": "3",
      "ccf_score": 70,
      "pfhd": 2.5e-8,                              // optional, enables PFHd summing
      "channels": [
        [{"name": "Switch A", "b10d": 2000000, "dc": 0.99}],
        [{"name": "Switch B", "mttfd_years": 120, "dc": 0.99}]
      ]
    }
  ]
}
```

Each channel is a list of components in series. Components take either `mttfd_years` or `b10d` (which needs the `operation` block).

## Rules encoded

| Item | Rule |
|---|---|
| MTTFd bands | low 3 to <10 y, medium 10 to <30 y, high 30 y and up; capped at 100 y (2500 y for category 4) |
| DCavg bands | none <60 %, low 60 to <90 %, medium 90 to <99 %, high 99 % and up |
| CCF | categories 2, 3 and 4 need at least 65 points |
| Category limits | B: DC none, MTTFd low/medium · 1: MTTFd high · 2 and 3: DC low/medium · 4: DC high, MTTFd high |
| Combining by count | PL of the weakest subsystem, one level lower if more than 3 (a, d, e) or 2 (b, c) subsystems share it |
| PFHd bands | a 1e-5 to 1e-4 · b 3e-6 to 1e-5 · c 1e-6 to 3e-6 · d 1e-7 to 1e-6 · e 1e-8 to 1e-7 per hour |

All of it lives in `iso13849_pl/core.py` and is covered by tests.

## What it does not do

It does not replace SISTEMA or the standard. It does not assess systematic failures, safety-related software (clause 4.6), fault exclusions, or validation per ISO 13849-2. Use it to check a design direction quickly and to catch the obvious misses (a missing CCF score, a single channel claimed as category 3, a wear part that needs replacing before the machine's mission time).

## Tests

```
pip install pytest
pytest
```

## License

MIT. Built by [Tsadi Shvo](https://www.linkedin.com/in/tsadishvo/), product safety and compliance for robotics, EV/BESS and power electronics.
