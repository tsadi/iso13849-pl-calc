import json
from pathlib import Path

import pytest

from iso13849_pl import core
from iso13849_pl.cli import evaluate, main, render_markdown

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "cobot_cell_estop.json"


@pytest.mark.parametrize("s,f,p,expected", [
    (1, 1, 1, "a"), (1, 1, 2, "b"), (1, 2, 1, "b"), (1, 2, 2, "c"),
    (2, 1, 1, "c"), (2, 1, 2, "d"), (2, 2, 1, "d"), (2, 2, 2, "e"),
])
def test_risk_graph(s, f, p, expected):
    assert core.plr_from_risk_graph(s, f, p) == expected


def test_risk_graph_rejects_bad_input():
    with pytest.raises(core.InputError):
        core.plr_from_risk_graph(3, 1, 1)


def test_mttfd_from_b10d():
    nop = core.nop_per_year(220, 16, 3600)  # one operation per hour
    assert nop == pytest.approx(3520)
    assert core.mttfd_from_b10d(1_000_000, nop) == pytest.approx(1_000_000 / 352)
    assert core.t10d_years(1_000_000, nop) == pytest.approx(1_000_000 / 3520)


def test_series_and_symmetrise():
    assert core.mttfd_series([100, 100]) == pytest.approx(50)
    # identical channels symmetrise to the same value
    assert core.mttfd_symmetrise(40, 40) == pytest.approx(40)
    assert core.mttfd_symmetrise(100, 10) == pytest.approx((2 / 3) * (110 - 1 / (0.01 + 0.1)))


def test_bands():
    assert core.mttfd_band(5) == "low"
    assert core.mttfd_band(10) == "medium"
    assert core.mttfd_band(30) == "high"
    with pytest.raises(core.InputError):
        core.mttfd_band(2)
    assert core.dc_band(0.5) == "none"
    assert core.dc_band(0.6) == "low"
    assert core.dc_band(0.9) == "medium"
    assert core.dc_band(0.99) == "high"


def test_dc_avg_weights_by_mttfd():
    # the lower-MTTFd part dominates
    assert core.dc_avg([(0.99, 10), (0.0, 100)]) == pytest.approx((0.099) / (0.11))


@pytest.mark.parametrize("cat,mttfd,dc,ccf,expected", [
    ("B", 5, None, None, "a"),
    ("B", 20, None, None, "b"),
    ("1", 50, None, None, "c"),
    ("2", 50, 0.95, 70, "d"),
    ("3", 20, 0.95, 70, "d"),
    ("3", 50, 0.80, 70, "d"),
    ("3", 5, 0.95, 70, "c"),
    ("4", 80, 0.99, 70, "e"),
])
def test_pl_simplified(cat, mttfd, dc, ccf, expected):
    assert core.pl_simplified(cat, mttfd, dc, ccf).pl == expected


def test_category3_high_dc_reads_as_medium():
    r = core.pl_simplified("3", 50, 0.995, 70)
    assert r.pl == "d"
    assert any("read as 'medium'" in n for n in r.notes)


def test_ccf_failure_blocks_category():
    r = core.pl_simplified("3", 50, 0.95, 50)
    assert r.pl is None


def test_category4_needs_high_dc():
    assert core.pl_simplified("4", 80, 0.95, 70).pl is None


def test_category1_needs_high_mttfd():
    assert core.pl_simplified("1", 20).pl is None


def test_mttfd_cap():
    assert core.pl_simplified("3", 500, 0.95, 70).mttfd_years == 100
    assert core.pl_simplified("4", 500, 0.99, 70).mttfd_years == 500


@pytest.mark.parametrize("pls,expected", [
    (["d", "d", "d"], "d"), (["d", "d", "d", "d"], "c"),
    (["e", "d"], "d"), (["c", "c"], "c"), (["c", "c", "c"], "b"),
    (["a", "a", "a", "a"], None),
])
def test_combine_by_count(pls, expected):
    assert core.combine_by_count(pls) == expected


def test_pfhd():
    assert core.pl_from_pfhd(5e-7) == "d"
    assert core.pl_from_pfhd(2e-6) == "c"
    total, pl = core.combine_by_pfhd([2e-8, 4e-8, 1e-7])
    assert total == pytest.approx(1.6e-7) and pl == "d"


def test_example_end_to_end():
    r = evaluate(json.loads(EXAMPLE.read_text()))
    assert r["plr"] == "d"
    assert r["overall"] == "d"
    md = render_markdown(r)
    assert "meets PLr d" in md


def test_cli_plr(capsys):
    assert main(["plr", "--s", "2", "--f", "1", "--p", "2"]) == 0
    assert capsys.readouterr().out.strip() == "d"
