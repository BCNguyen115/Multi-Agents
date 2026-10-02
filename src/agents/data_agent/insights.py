"""Insight engine: deterministic, evidence-carrying facts about a dataset.

Each generator returns :class:`Insight` objects holding *numbers and column references only* — no prose.
Prose is produced later (story.py) strictly from these numbers, which is what makes every sentence in the
final story checkable against the data.

Generators: trend, period change, contribution to change, composition/concentration, ranking, group
difference (significance tested), correlation, distribution/outliers, time anomalies.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy import stats

from src.agents.data_agent import compute
from src.agents.data_agent.profiler import AGG_SUM, ROLE_IDENTIFIER
from src.shared.logger import get_logger

logger: logging.Logger = get_logger(__name__)

MAX_MEASURES = 3
MAX_DIMS = 3
MAX_FACTS = 16
_MAX_PER_KIND = 3
_STAT_SAMPLE = 20_000
_MAX_CATEGORIES = 200


@dataclass
class Insight:
    """One verifiable finding: ``numbers`` are the evidence, ``refs`` the columns involved."""

    kind: str
    importance: float
    confidence: float
    numbers: dict[str, Any]
    refs: dict[str, Any]
    id: str = ""
    caveats: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Insight":
        """Rebuild a fact from its JSON form (used by the verifier on a finished dashboard spec)."""
        return cls(
            kind=data["kind"], importance=data["importance"], confidence=data["confidence"], numbers=data["numbers"],
            refs=data["refs"], id=data["id"], caveats=data.get("caveats", []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "importance": round(self.importance, 4),
            "confidence": round(self.confidence, 4),
            "numbers": self.numbers,
            "refs": self.refs,
            "caveats": self.caveats,
        }


def _num(value: Any) -> Optional[float]:
    """JSON-safe float (NaN/inf -> None)."""
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _agg_of(profile: dict[str, Any], measure: Optional[str]) -> str:
    if measure is None:
        return "count"
    return "sum" if profile["policies"].get(measure, {}).get("agg") == AGG_SUM else "avg"


def _sample(df: pd.DataFrame) -> pd.DataFrame:
    return df if len(df) <= _STAT_SAMPLE else df.sample(n=_STAT_SAMPLE, random_state=0)


def _usable_dims(df: pd.DataFrame, profile: dict[str, Any]) -> list[str]:
    """Dimensions worth analysing: 2..200 distinct values, not identifiers, not the time axis."""
    out = []
    for dim in profile["dimensions"]:
        info = profile["columns"][dim]
        if info["role"] == ROLE_IDENTIFIER or not 2 <= info["nunique"] <= _MAX_CATEGORIES:
            continue
        out.append(dim)
    return out


# ---------------------------------------------------------------------------
# Time based
# ---------------------------------------------------------------------------


def _series(df: pd.DataFrame, profile: dict[str, Any], measure: Optional[str], freq: Optional[str] = None) -> tuple[pd.DataFrame, list[str]]:
    """Period series for the primary time axis, edge periods that are only partially observed removed for totals."""
    time = profile["time"]
    agg = _agg_of(profile, measure)
    raw = compute.period_series(df, time["primary"], measure, agg, freq or time["freq"])
    trimmed = compute.trim_partial(raw, additive=agg in ("sum", "count"))
    dropped = raw.loc[~raw["label"].isin(trimmed["label"]), "label"].tolist()
    return trimmed, dropped


def _trend(df: pd.DataFrame, profile: dict[str, Any], measure: Optional[str]) -> Optional[Insight]:
    series, dropped = _series(df, profile, measure)
    n = len(series)
    if n < 6:
        return None
    y = series["value"].to_numpy(dtype=float)
    x = np.arange(n)
    # Robust to outliers (a single spike must not hide a real trend): Spearman for monotonicity,
    # Theil–Sen for the slope, and medians of the first/last windows for the level change.
    rho = stats.spearmanr(x, y)[0] if np.ptp(y) > 0 else 0.0
    rho = float(rho) if math.isfinite(rho) else 0.0
    slope = float(stats.theilslopes(y, x)[0])
    k = max(1, n // 4)
    first_level, last_level = float(np.median(y[:k])), float(np.median(y[-k:]))
    pct = (last_level - first_level) / abs(first_level) if first_level else None

    if pct is None or abs(pct) < 0.02 or abs(rho) < 0.2:
        direction = "flat"
    else:
        direction = "up" if pct > 0 else "down"

    peak, trough = int(np.argmax(y)), int(np.argmin(y))
    years = (series["period"].iloc[-1].start_time - series["period"].iloc[0].start_time).days / 365.25
    cagr = (last_level / first_level) ** (1 / years) - 1 if years >= 2 and first_level > 0 and last_level > 0 else None

    strength = 0.15 if direction == "flat" else _clip(abs(pct)) * (0.35 + 0.65 * abs(rho))
    return Insight(
        kind="trend",
        importance=strength,
        confidence=_clip(0.4 + 0.6 * min(n, 24) / 24) * (0.5 + 0.5 * abs(rho)),
        numbers={
            "grain": profile["time"]["grain"],
            "n_periods": n,
            "window": k,
            "first_period": series["label"].iloc[0],
            "last_period": series["label"].iloc[-1],
            "first_avg": _num(first_level),
            "last_avg": _num(last_level),
            "pct_change": _num(pct),
            "direction": direction,
            "rho": _num(rho),
            "slope": _num(slope),
            "peak_period": series["label"].iloc[peak],
            "peak_value": _num(y[peak]),
            "trough_period": series["label"].iloc[trough],
            "trough_value": _num(y[trough]),
            "cagr": _num(cagr),
            "years": _num(years),
        },
        refs={"measure": measure, "time": profile["time"]["primary"]},
        caveats=[{"code": "partial_period_excluded", "periods": dropped}] if dropped else [],
    )


def _period_change(df: pd.DataFrame, profile: dict[str, Any], measure: Optional[str]) -> Optional[Insight]:
    if profile["time"]["freq"] not in ("W", "M", "Q", "Y"):
        return None
    series, dropped = _series(df, profile, measure)
    if len(series) < 2:
        return None
    last, prev = series.iloc[-1], series.iloc[-2]
    delta = float(last["value"] - prev["value"])
    pct = delta / abs(prev["value"]) if prev["value"] else None

    yoy_lag = {"M": 12, "Q": 4}.get(profile["time"]["freq"])
    yoy = series.iloc[-1 - yoy_lag] if yoy_lag and len(series) > yoy_lag else None
    yoy_pct = (last["value"] - yoy["value"]) / abs(yoy["value"]) if yoy is not None and yoy["value"] else None

    return Insight(
        kind="period_change",
        importance=0.9 * _clip(abs(pct)) if pct is not None else 0.3,
        confidence=0.85,
        numbers={
            "grain": profile["time"]["grain"],
            "last_period": last["label"],
            "last_value": _num(last["value"]),
            "prev_period": prev["label"],
            "prev_value": _num(prev["value"]),
            "delta": _num(delta),
            "delta_pct": _num(pct),
            "yoy_period": yoy["label"] if yoy is not None else None,
            "yoy_value": _num(yoy["value"]) if yoy is not None else None,
            "yoy_pct": _num(yoy_pct),
        },
        refs={"measure": measure, "time": profile["time"]["primary"]},
        caveats=[{"code": "partial_period_excluded", "periods": dropped}] if dropped else [],
    )


def _contribution(df: pd.DataFrame, profile: dict[str, Any], measure: str, dim: str) -> Optional[Insight]:
    """Which categories drove the change between the last two complete periods (additive measures only)."""
    freq = profile["time"]["freq"]
    if freq == "D":
        if profile["time"]["span_days"] < 28:
            return None
        freq = "W"
    series, _ = _series(df, profile, measure, freq)
    if len(series) < 2:
        return None
    p0, p1 = series["period"].iloc[-2], series["period"].iloc[-1]

    periods = compute.as_datetime(df, profile["time"]["primary"]).dt.to_period(freq)
    window = df.loc[periods.isin([p0, p1])]
    if window.empty:
        return None
    pivot = (
        pd.DataFrame({"dim": window[dim].astype("string"), "p": periods[window.index], "v": compute.as_numeric(window[measure])})
        .dropna(subset=["dim"])
        .groupby(["dim", "p"])["v"].sum().unstack(fill_value=0.0)
        .reindex(columns=[p0, p1], fill_value=0.0)
    )
    delta = pivot[p1] - pivot[p0]
    total_before, total_delta, gross = float(pivot[p0].sum()), float(delta.sum()), float(delta.abs().sum())
    if gross == 0 or total_before == 0 or abs(total_delta) / abs(total_before) < 0.03:
        return None

    # A big category naturally takes a big slice of any change. What *drives* the change is the part beyond
    # growing in proportion to its size, so contributors are ranked by that excess movement.
    excess = delta - (pivot[p0] / total_before) * total_delta
    excess_total = float(excess.abs().sum())
    top = excess.reindex(excess.abs().sort_values(ascending=False, kind="mergesort").index).head(3).index
    contributors = [{"name": str(name), "delta": _num(delta[name]), "share_of_gross": _num(abs(delta[name]) / gross), "excess": _num(excess[name])} for name in top]
    k = len(excess)
    top_share = float(excess.abs().max() / excess_total) if excess_total else 0.0
    driver_strength = _clip((top_share - 1 / k) / (1 - 1 / k)) if k > 1 else 0.0  # beyond what k equal movers would show
    delta_pct = total_delta / abs(total_before)
    return Insight(
        kind="contribution",
        importance=_clip(abs(delta_pct)) * (0.3 + 0.7 * driver_strength),
        confidence=0.8,
        numbers={
            "grain": {"W": "week", "M": "month", "Q": "quarter", "Y": "year"}[freq],
            "from_period": compute.period_label(p0, freq),
            "to_period": compute.period_label(p1, freq),
            "from_total": _num(total_before),
            "to_total": _num(float(pivot[p1].sum())),
            "delta": _num(total_delta),
            "delta_pct": _num(delta_pct),
            "contributors": contributors,
        },
        refs={"measure": measure, "dimension": dim, "time": profile["time"]["primary"]},
    )


def _anomalies(df: pd.DataFrame, profile: dict[str, Any], measure: Optional[str]) -> Optional[Insight]:
    """Periods far from the local level (robust z-score on residuals of a rolling median)."""
    series, _ = _series(df, profile, measure)
    n = len(series)
    if n < 12:
        return None
    y = series["value"].astype(float)
    window = max(5, (n // 8) | 1)
    expected = y.rolling(window, center=True, min_periods=1).median()
    resid = y - expected
    centre = float(resid.median())
    mad = float((resid - centre).abs().median())
    scale = mad / 0.6745 if mad > 0 else float(resid.std())
    if not scale or not math.isfinite(scale):
        return None
    z = (resid - centre) / scale
    flagged = z[z.abs() > 3.5].abs().sort_values(ascending=False).head(3)
    if flagged.empty:
        return None
    points = []
    for idx in flagged.index:
        exp = float(expected.iloc[idx])
        points.append({
            "period": series["label"].iloc[idx],
            "value": _num(y.iloc[idx]),
            "expected": _num(exp),
            "deviation_pct": _num((y.iloc[idx] - exp) / abs(exp)) if exp else None,
            "z": _num(z.iloc[idx]),
        })
    return Insight(
        kind="anomaly",
        importance=0.8 * _clip(float(flagged.iloc[0]) / 10.0),
        confidence=0.7,
        numbers={"grain": profile["time"]["grain"], "points": points, "n_periods": n},
        refs={"measure": measure, "time": profile["time"]["primary"]},
    )


# ---------------------------------------------------------------------------
# Cross-sectional
# ---------------------------------------------------------------------------


def _composition(df: pd.DataFrame, profile: dict[str, Any], dim: str, measure: Optional[str]) -> Optional[Insight]:
    """Share of the total (or of the records) held by each category; concentration via top-N share and HHI."""
    agg = _agg_of(profile, measure)
    basis = "sum" if agg == "sum" else "count"
    grouped = compute.group_aggregate(df, dim, measure if basis == "sum" else None, "sum" if basis == "sum" else "count")
    grouped = grouped[grouped["value"] > 0]
    n_groups = len(grouped)
    if n_groups < 2 or len(df) / n_groups < 2:
        return None  # a category per row has no "composition"
    total = float(grouped["value"].sum())
    shares = grouped["value"] / total
    hhi = float((shares**2).sum())
    cumulative = shares.cumsum()
    top1 = grouped.iloc[0]
    return Insight(
        kind="composition",
        importance=0.8 * _clip(max(float(shares.iloc[0]), 1.5 * hhi)),
        confidence=0.9,
        numbers={
            "basis": basis,
            "n_groups": n_groups,
            "total": _num(total),
            "top1": str(top1["name"]),
            "top1_value": _num(top1["value"]),
            "top1_share": _num(shares.iloc[0]),
            "top3_share": _num(shares.head(3).sum()),
            "hhi": _num(hhi),
            "pareto_n": int((cumulative < 0.8).sum() + 1),
        },
        refs={"measure": measure if basis == "sum" else None, "dimension": dim},
    )


def _ranking(df: pd.DataFrame, profile: dict[str, Any], dim: str, measure: Optional[str]) -> Optional[Insight]:
    agg = _agg_of(profile, measure)
    min_group = max(5, int(0.005 * len(df))) if agg == "avg" else 1
    grouped = compute.group_aggregate(df, dim, measure, agg, min_group=min_group)
    if len(grouped) < 3:
        return None
    mean_value = float(grouped["value"].mean())
    top, second, bottom = grouped.iloc[0], grouped.iloc[1], grouped.iloc[-1]
    ratio = float(top["value"] / mean_value) if mean_value else None
    gap = float((top["value"] - second["value"]) / abs(second["value"])) if second["value"] else None
    # Ranking by a *sum* mostly restates group size, which the composition fact already covers.
    dampen = 0.5 if agg == "sum" else 1.0
    return Insight(
        kind="ranking",
        importance=0.55 * dampen * _clip(((ratio or 1.0) - 1.0) / 2.0 + 0.25),
        confidence=0.85,
        numbers={
            "agg": agg,
            "n_groups": len(grouped),
            "top1": str(top["name"]),
            "top1_value": _num(top["value"]),
            "top2": str(second["name"]),
            "top2_value": _num(second["value"]),
            "bottom1": str(bottom["name"]),
            "bottom1_value": _num(bottom["value"]),
            "mean_of_groups": _num(mean_value),
            "ratio_to_mean": _num(ratio),
            "gap_to_second_pct": _num(gap),
        },
        refs={"measure": measure, "dimension": dim},
    )


def _group_difference(df: pd.DataFrame, profile: dict[str, Any], dim: str, measure: str, alpha: float) -> Optional[Insight]:
    """Kruskal–Wallis across the biggest groups; reported only when significant *and* the effect is not tiny."""
    frame = pd.DataFrame({"g": df[dim].astype("string"), "v": compute.as_numeric(df[measure])}).dropna()
    sizes = frame["g"].value_counts()
    keep = sizes[sizes >= 10].head(12).index
    frame = frame[frame["g"].isin(keep)]
    groups = [g["v"].to_numpy() for _, g in frame.groupby("g")]
    if len(groups) < 2 or len(frame) < 30:
        return None
    try:
        h_stat, p_value = stats.kruskal(*groups)
    except ValueError:  # all values identical
        return None
    k, n = len(groups), len(frame)
    eps2 = float(max((h_stat - k + 1) / (n - k), 0.0))
    if not (p_value < alpha and eps2 >= 0.02):
        return None
    means = frame.groupby("g")["v"].mean().sort_values(ascending=False)
    best, worst = means.index[0], means.index[-1]
    diff_pct = float((means.iloc[0] - means.iloc[-1]) / abs(means.iloc[-1])) if means.iloc[-1] else None
    return Insight(
        kind="group_difference",
        importance=0.7 * _clip(eps2 * 5),
        confidence=_clip(1 - p_value / alpha * 0.5),
        numbers={
            "n_groups": k,
            "n": n,
            "best_group": str(best),
            "best_mean": _num(means.iloc[0]),
            "worst_group": str(worst),
            "worst_mean": _num(means.iloc[-1]),
            "diff_pct": _num(diff_pct),
            "effect_size": _num(eps2),
            "p_value": _num(p_value),
        },
        refs={"measure": measure, "dimension": dim},
    )


def _correlations(df: pd.DataFrame, profile: dict[str, Any]) -> list[Insight]:
    """Top rank correlations between numeric columns (Spearman, n >= 30, p < 0.01, |rho| >= 0.4)."""
    cols = (profile["measures"] + profile["ratio_cols"] + profile["ordinal_cols"])[:8]
    if len(cols) < 2:
        return []
    frame = _sample(df)
    found: list[Insight] = []
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            pair = frame[[a, b]].apply(compute.as_numeric).dropna()
            if len(pair) < 30 or pair[a].nunique() < 5 or pair[b].nunique() < 5:
                continue
            rho, p_value = stats.spearmanr(pair[a], pair[b])
            if not math.isfinite(rho) or abs(rho) < 0.4 or p_value >= 0.01 or abs(rho) > 0.98:
                continue  # weak/insignificant, or a near duplicate column (not a finding)
            found.append(Insight(
                kind="correlation",
                importance=0.65 * _clip((abs(rho) - 0.3) / 0.6),
                confidence=_clip(1 - p_value * 10) * min(1.0, len(pair) / 200),
                numbers={"rho": _num(rho), "n": len(pair), "p_value": _num(p_value), "direction": "positive" if rho > 0 else "negative"},
                refs={"a": a, "b": b},
                caveats=[{"code": "correlation_not_causation"}],
            ))
    return sorted(found, key=lambda x: -x.importance)[:3]


def _distribution(df: pd.DataFrame, profile: dict[str, Any], measure: str) -> Optional[Insight]:
    values = compute.as_numeric(df[measure]).dropna()
    n = len(values)
    if n < 30:
        return None
    q1, q3 = float(values.quantile(0.25)), float(values.quantile(0.75))
    iqr = q3 - q1
    outliers = int(((values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)).sum()) if iqr > 0 else 0
    skew = float(values.skew())
    additive = _agg_of(profile, measure) == "sum" and (values >= 0).all() and values.sum() > 0
    top1 = top10 = None
    if additive:
        ordered = values.sort_values(ascending=False).to_numpy()
        total = float(ordered.sum())
        top1 = float(ordered[: max(1, math.ceil(0.01 * n))].sum() / total)
        top10 = float(ordered[: max(1, math.ceil(0.10 * n))].sum() / total)
    outlier_share = outliers / n
    if not (abs(skew) > 1.5 or outlier_share >= 0.01 or (top10 or 0) >= 0.5):
        return None
    return Insight(
        kind="distribution",
        importance=0.5 * _clip(max(abs(skew) / 6, outlier_share * 5, (top10 or 0) - 0.3)),
        confidence=0.85,
        numbers={
            "n": n,
            "skew": _num(skew),
            "median": _num(values.median()),
            "mean": _num(values.mean()),
            "max": _num(values.max()),
            "outlier_count": outliers,
            "outlier_share": _num(outlier_share),
            "top1pct_share": _num(top1),
            "top10pct_share": _num(top10),
        },
        refs={"measure": measure},
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _safe(label: str, fn: Any, *args: Any) -> list[Insight]:
    """Run one generator; an analysis that cannot be computed is skipped, never fatal."""
    try:
        result = fn(*args)
    except Exception as exc:  # noqa: BLE001 - insight generation must degrade gracefully
        logger.warning("Insight generator '%s' skipped: %s", label, exc)
        return []
    if result is None:
        return []
    return result if isinstance(result, list) else [result]


def generate_insights(df: pd.DataFrame, profile: dict[str, Any], max_facts: int = MAX_FACTS) -> list[Insight]:
    """Compute, rank and id (``F1``, ``F2``, ...) the most informative facts about ``df``."""
    if df.empty:
        return []
    measures = profile["measures"][:MAX_MEASURES] or profile["ratio_cols"][:1] or profile["ordinal_cols"][:1]
    dims = _usable_dims(df, profile)[:MAX_DIMS]
    has_time = bool(profile["time"].get("primary"))
    primary = measures[0] if measures else None

    facts: list[Insight] = []
    if has_time:
        for measure in (measures[:2] or [None]):
            facts += _safe("trend", _trend, df, profile, measure)
            facts += _safe("period_change", _period_change, df, profile, measure)
        facts += _safe("anomalies", _anomalies, df, profile, primary)
        if primary and _agg_of(profile, primary) == "sum":
            for dim in dims:
                facts += _safe("contribution", _contribution, df, profile, primary, dim)

    for dim in dims:
        facts += _safe("composition", _composition, df, profile, dim, primary)
        for measure in (measures[:2] or [None]):
            facts += _safe("ranking", _ranking, df, profile, dim, measure)

    tests = max(1, len(dims) * len(measures[:MAX_MEASURES]))
    for dim in dims:
        if profile["columns"][dim]["nunique"] > 30:
            continue
        for measure in measures[:MAX_MEASURES]:
            facts += _safe("group_difference", _group_difference, df, profile, dim, measure, 0.05 / tests)

    facts += _safe("correlation", _correlations, df, profile)
    for measure in measures[:MAX_MEASURES]:
        facts += _safe("distribution", _distribution, df, profile, measure)

    ranked = sorted(facts, key=lambda f: (-(f.importance * f.confidence), f.kind, str(f.refs)))
    picked: list[Insight] = []
    per_kind: dict[str, int] = {}
    for fact in ranked:
        if per_kind.get(fact.kind, 0) >= _MAX_PER_KIND:
            continue
        per_kind[fact.kind] = per_kind.get(fact.kind, 0) + 1
        picked.append(fact)
        if len(picked) >= max_facts:
            break
    for index, fact in enumerate(picked, start=1):
        fact.id = f"F{index}"
    return picked
