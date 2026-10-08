"""Performance Level (PL) estimation per the ISO 13849-1 simplified procedure.

Covers the parts of ISO 13849-1 a safety engineer does by hand during
concept and design review:

* PLr from the risk graph (S, F, P)
* MTTFd from B10D for wear-based components
* channel MTTFd for components in series, and the two-channel
  symmetrisation formula
* DCavg across a channel
* MTTFd / DCavg banding
* PL from category + MTTFd band + DCavg band (the bar-chart method)
* combining subsystems into one safety function (by PL count, or by
  summing PFHd values when you have them)

This is an engineering aid. It does not replace a validated tool such as
SISTEMA or the standard itself, and it does not check systematic
failures, software (clause 4.6) or validation (ISO 13849-2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

PL_ORDER = ["a", "b", "c", "d", "e"]

# PFHd band for each PL (1/h), lower bound inclusive, upper bound exclusive.
PFHD_BANDS = {
    "a": (1e-5, 1e-4),
    "b": (3e-6, 1e-5),
    "c": (1e-6, 3e-6),
    "d": (1e-7, 1e-6),
    "e": (1e-8, 1e-7),
}

CATEGORIES = ["B", "1", "2", "3", "4"]


class InputError(ValueError):
    """Raised when inputs fall outside what the method can evaluate."""


# ---------------------------------------------------------------- risk graph

def plr_from_risk_graph(s: int, f: int, p: int) -> str:
    """Required PL from the ISO 13849-1 risk graph.

    s: severity 1 (slight, reversible) or 2 (serious, irreversible or death)
    f: frequency/duration of exposure 1 (seldom/short) or 2 (frequent/long)
    p: possibility of avoidance 1 (possible) or 2 (scarcely possible)
    """
    for name, v in (("S", s), ("F", f), ("P", p)):
        if v not in (1, 2):
            raise InputError(f"{name} must be 1 or 2, got {v!r}")
    # Walk the graph: each '2' moves one step up, starting from 'a'.
    index = (s - 1) * 2 + (f - 1) + (p - 1)
    return PL_ORDER[index]


# ------------------------------------------------------------------- MTTFd

def nop_per_year(days_per_year: float, hours_per_day: float, cycle_time_s: float) -> float:
    """Mean number of operations per year."""
    if cycle_time_s <= 0:
        raise InputError("cycle time must be > 0 s")
    if not (0 < days_per_year <= 366) or not (0 < hours_per_day <= 24):
        raise InputError("days per year must be 1..366 and hours per day 0..24")
    return days_per_year * hours_per_day * 3600.0 / cycle_time_s


def mttfd_from_b10d(b10d: float, nop: float) -> float:
    """MTTFd in years for a wear-based component: B10D / (0.1 * nop)."""
    if b10d <= 0 or nop <= 0:
        raise InputError("B10D and nop must be > 0")
    return b10d / (0.1 * nop)


def t10d_years(b10d: float, nop: float) -> float:
    """T10D: time until 10 % of components fail dangerously (replace before this)."""
    return b10d / nop


def mttfd_series(values: Iterable[float]) -> float:
    """MTTFd of components in series within one channel (parts count)."""
    vals = list(values)
    if not vals or any(v <= 0 for v in vals):
        raise InputError("need at least one positive MTTFd value")
    return 1.0 / sum(1.0 / v for v in vals)


def mttfd_symmetrise(c1: float, c2: float) -> float:
    """Equivalent MTTFd for two channels with different MTTFd values."""
    if c1 <= 0 or c2 <= 0:
        raise InputError("channel MTTFd values must be > 0")
    return (2.0 / 3.0) * (c1 + c2 - 1.0 / (1.0 / c1 + 1.0 / c2))


def cap_mttfd(mttfd: float, category: str) -> float:
    """Cap MTTFd per channel: 100 years, or 2500 years for category 4 (2023 edition)."""
    cap = 2500.0 if category == "4" else 100.0
    return min(mttfd, cap)


def mttfd_band(mttfd: float) -> str:
    if mttfd < 3:
        raise InputError("MTTFd below 3 years is not acceptable for any category")
    if mttfd < 10:
        return "low"
    if mttfd < 30:
        return "medium"
    return "high"


# ---------------------------------------------------------------------- DC

def dc_avg(items: Iterable[tuple[float, float]]) -> float:
    """DCavg from (dc_fraction, mttfd_years) pairs for every component."""
    pairs = list(items)
    if not pairs:
        raise InputError("need at least one (DC, MTTFd) pair")
    num = den = 0.0
    for dc, m in pairs:
        if not 0 <= dc <= 1:
            raise InputError(f"DC must be a fraction 0..1, got {dc}")
        if m <= 0:
            raise InputError("MTTFd must be > 0")
        num += dc / m
        den += 1.0 / m
    return num / den


def dc_band(dc: float) -> str:
    dc = round(dc, 6)  # avoid 0.8999999 falling into the lower band
    if dc < 0.60:
        return "none"
    if dc < 0.90:
        return "low"
    if dc < 0.99:
        return "medium"
    return "high"


# ---------------------------------------------------- simplified PL lookup

# (category, dc_band) -> {mttfd_band: PL}; missing entries are not allowed.
_PL_TABLE = {
    ("B", "none"): {"low": "a", "medium": "b"},
    ("1", "none"): {"high": "c"},
    ("2", "low"): {"low": "a", "medium": "b", "high": "c"},
    ("2", "medium"): {"low": "b", "medium": "c", "high": "d"},
    ("3", "low"): {"low": "b", "medium": "c", "high": "d"},
    ("3", "medium"): {"low": "c", "medium": "d", "high": "d"},
    ("4", "high"): {"high": "e"},
}


@dataclass
class PLResult:
    pl: Optional[str]
    category: str
    mttfd_years: float
    mttfd_band: str
    dc_avg: Optional[float]
    dc_band: str
    ccf_score: Optional[int]
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.pl is not None


def pl_simplified(category: str, mttfd_years: float, dcavg: Optional[float] = None,
                  ccf_score: Optional[int] = None) -> PLResult:
    """Estimate PL from category, channel MTTFd and DCavg.

    Higher DC than the category needs is clamped down to the band the
    category uses (e.g. category 3 with DC 99 % is read as 'medium').
    """
    category = str(category).upper()
    if category not in CATEGORIES:
        raise InputError(f"category must be one of {CATEGORIES}")
    notes: list[str] = []

    capped = cap_mttfd(mttfd_years, category)
    if capped < mttfd_years:
        notes.append(f"MTTFd capped at {capped:g} years for category {category}.")
    mband = mttfd_band(capped)
    dband = dc_band(dcavg) if dcavg is not None else "none"

    allowed = {d for (c, d) in _PL_TABLE if c == category}
    order = ["none", "low", "medium", "high"]
    used = dband
    if used not in allowed:
        lower = [d for d in allowed if order.index(d) <= order.index(dband)]
        if lower:
            used = max(lower, key=order.index)
            if used != dband:
                notes.append(f"DCavg band '{dband}' read as '{used}' for category {category}.")
        else:
            notes.append(f"Category {category} needs DCavg of at least "
                         f"'{min(allowed, key=order.index)}'; got '{dband}'.")
            return PLResult(None, category, capped, mband, dcavg, dband, ccf_score, notes)

    if category in ("2", "3", "4"):
        if ccf_score is None:
            notes.append("CCF score not given; categories 2-4 need >= 65 points.")
        elif ccf_score < 65:
            notes.append(f"CCF score {ccf_score} < 65: category {category} is not met.")
            return PLResult(None, category, capped, mband, dcavg, dband, ccf_score, notes)

    pl = _PL_TABLE[(category, used)].get(mband)
    if pl is None:
        notes.append(f"Category {category} does not allow MTTFd band '{mband}'.")
    return PLResult(pl, category, capped, mband, dcavg, dband, ccf_score, notes)


def meets(pl: Optional[str], plr: str) -> bool:
    return pl is not None and PL_ORDER.index(pl) >= PL_ORDER.index(plr)


# ------------------------------------------------- combining subsystems

def combine_by_count(pls: Iterable[str]) -> Optional[str]:
    """Combine series subsystems by lowest PL and how many share it.

    Rule: PL_low stays if at most N subsystems share it, otherwise drops
    one level (N = 3 for a, d, e; N = 2 for b, c). Returns None when the
    result would fall below 'a'.
    """
    vals = [p.lower() for p in pls]
    if not vals or any(p not in PL_ORDER for p in vals):
        raise InputError("PL values must be a..e")
    low = min(vals, key=PL_ORDER.index)
    n = vals.count(low)
    limit = 2 if low in ("b", "c") else 3
    if n <= limit:
        return low
    i = PL_ORDER.index(low) - 1
    return PL_ORDER[i] if i >= 0 else None


def pl_from_pfhd(pfhd: float) -> Optional[str]:
    for pl in reversed(PL_ORDER):
        lo, hi = PFHD_BANDS[pl]
        if lo <= pfhd < hi:
            return pl
    if pfhd < PFHD_BANDS["e"][0]:
        return "e"
    return None


def combine_by_pfhd(values: Iterable[float]) -> tuple[float, Optional[str]]:
    total = sum(values)
    return total, pl_from_pfhd(total)
