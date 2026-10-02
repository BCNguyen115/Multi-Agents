"""run_rag_eval quality gate: absolute minimums plus a regression limit against the last accepted run."""
import json
from argparse import Namespace

import pytest

from scripts.run_rag_eval import check_gate

RETRIEVAL = {"rerank": {}, "modes": {"plan": {"hit@5": 0.58, "mrr": 0.44}}}


def gate(tmp_path, baseline=None):
    path = tmp_path / "baseline.json"
    if baseline is not None:
        path.write_text(json.dumps(baseline), encoding="utf-8")
    args = Namespace(gate_on="plan", min_hit5=0.5, min_mrr=0.4, baseline=str(path), max_drop=0.03, save_baseline="")
    check_gate(RETRIEVAL, args)


def test_without_a_baseline_only_the_minimums_apply(tmp_path):
    gate(tmp_path)


def test_a_drop_beyond_max_drop_against_the_baseline_fails_even_above_the_minimum(tmp_path):
    with pytest.raises(SystemExit):
        gate(tmp_path, baseline={"hit@5": 0.65, "mrr": 0.44})  # 0.58 is above 0.5 but 0.07 below the accepted run
    gate(tmp_path, baseline={"hit@5": 0.60, "mrr": 0.45})      # within 0.03: passes


def test_a_passing_run_can_become_the_new_baseline(tmp_path):
    args = Namespace(gate_on="plan", min_hit5=0.5, min_mrr=0.4, baseline="", max_drop=0.03, save_baseline=str(tmp_path / "new.json"))
    check_gate(RETRIEVAL, args)
    assert json.loads((tmp_path / "new.json").read_text(encoding="utf-8")) == {"hit@5": 0.58, "mrr": 0.44}
