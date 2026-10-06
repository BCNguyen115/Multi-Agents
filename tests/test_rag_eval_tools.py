"""The evaluation tools: bootstrap intervals, run-time overrides, and the paired comparison of two runs."""
import pytest

from scripts.compare_rag_eval import paired_difference
from scripts.run_rag_eval import apply_overrides, bootstrap_ci
from src.config import settings


def test_the_interval_contains_the_point_estimate_and_narrows_with_more_questions():
    few = [1, None, 3, 2, None, 1, 7, 2]
    many = few * 25
    for ranks in (few, many):
        ci = bootstrap_ci(ranks)
        point = sum(1 for r in ranks if r and r <= 5) / len(ranks)
        assert ci["hit@5"][0] <= point <= ci["hit@5"][1]
    assert bootstrap_ci(many)["mrr"][1] - bootstrap_ci(many)["mrr"][0] < bootstrap_ci(few)["mrr"][1] - bootstrap_ci(few)["mrr"][0]


def test_a_real_gain_on_the_same_questions_is_called_better_and_noise_is_not():
    before = [3, None, 2, 5, None, 4, 1, None, 6, 2] * 6
    after = [1, 4, 1, 2, 3, 1, 1, 5, 3, 1] * 6          # every question improves
    assert paired_difference(before, after)["mrr"]["verdict"] == "better"
    same = paired_difference(before, list(before))
    assert same["mrr"]["difference"] == 0 and same["mrr"]["verdict"] == "no clear difference"
    worse = paired_difference(after, before)
    assert worse["hit@5"]["verdict"] == "worse"


def test_a_small_mixed_change_is_not_called_better():
    before = [1, 2, None, 4, 5, None, 1, 3]
    after = [2, 1, None, 5, 4, None, 1, 3]              # a few swaps, nothing gained overall
    assert paired_difference(before, after)["mrr"]["verdict"] == "no clear difference"


def test_runs_over_different_questions_cannot_be_compared():
    with pytest.raises(ValueError):
        paired_difference([1, 2], [1, 2, 3])


def test_set_overrides_read_the_value_as_the_settings_own_type(monkeypatch):
    for key in ("RAG_FTS_SOURCE", "RAG_FTS_STOPWORDS", "RAG_HNSW_EF_SEARCH", "RAG_MIN_VECTOR_SCORE"):
        monkeypatch.setattr(settings, key, getattr(settings, key))
    applied = apply_overrides(["RAG_FTS_SOURCE=passage", "RAG_FTS_STOPWORDS=true", "RAG_HNSW_EF_SEARCH=80", "RAG_MIN_VECTOR_SCORE=0.35"])
    assert applied == {"RAG_FTS_SOURCE": "passage", "RAG_FTS_STOPWORDS": True, "RAG_HNSW_EF_SEARCH": 80, "RAG_MIN_VECTOR_SCORE": 0.35}
    assert settings.RAG_FTS_STOPWORDS is True and settings.RAG_HNSW_EF_SEARCH == 80


def test_set_refuses_a_name_that_is_not_a_setting():
    with pytest.raises(SystemExit):
        apply_overrides(["RAG_NO_SUCH_THING=1"])
