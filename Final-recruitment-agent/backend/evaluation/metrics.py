"""Plain-Python metrics (no libraries), small enough to check by hand. See tests/test_eval_metrics.py."""
import math
from collections import Counter

LABELS = ["suitable", "needs_review", "not_suitable"]


def graded_relevance(reference_ranking: list[str]) -> dict[str, int]:
    """The reference ranking becomes gains: the best candidate gets n, the next n-1, ... the last 1.
    Anyone not in the reference ranking has gain 0."""
    n = len(reference_ranking)
    return {cid: n - i for i, cid in enumerate(reference_ranking)}


def dcg(gains: list[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(system_ranking: list[str], reference_ranking: list[str], k: int) -> float:
    """How close the system's top-k is to the reference order (1.0 = same top-k, order included)."""
    rel = graded_relevance(reference_ranking)
    ideal = dcg(sorted(rel.values(), reverse=True)[:k])
    if ideal == 0:
        return 0.0
    return dcg([rel.get(cid, 0) for cid in system_ranking[:k]]) / ideal


def precision_at_k(system_ranking: list[str], accepted: list[str], k: int) -> float:
    """Share of the top-k slots held by candidates the reference calls suitable.
    The denominator is always k: if the system ranked fewer than k candidates, the empty slots count as misses."""
    return sum(1 for cid in system_ranking[:k] if cid in set(accepted)) / k


def recall_at_k(system_ranking: list[str], accepted: list[str], k: int) -> float:
    if not accepted:
        return 0.0
    return sum(1 for cid in system_ranking[:k] if cid in set(accepted)) / len(accepted)


def classification_report(reference: list[str], predicted: list[str], labels: list[str] = LABELS) -> dict:
    """Accuracy, confusion matrix and per-class precision/recall/F1. A prediction outside `labels`
    (for example "error": no decision was produced) is kept as an extra column and counts as wrong."""
    assert len(reference) == len(predicted)
    columns = labels + sorted({p for p in predicted if p not in labels})
    matrix = {r: {c: 0 for c in columns} for r in labels}
    for r, p in zip(reference, predicted):
        matrix[r][p] += 1
    per_class = {}
    for lab in labels:
        tp = matrix[lab][lab]
        fp = sum(matrix[o][lab] for o in labels if o != lab)
        fn = sum(matrix[lab][c] for c in columns if c != lab)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        f1 = 2 * prec * rec / (prec + rec) if prec and rec else (0.0 if prec is not None and rec is not None else None)
        per_class[lab] = {"precision": prec, "recall": rec, "f1": f1, "support": tp + fn}
    scored = [v for v in per_class.values() if v["f1"] is not None]
    return {
        "total": len(reference),
        "correct": sum(matrix[l][l] for l in labels),
        "accuracy": (sum(matrix[l][l] for l in labels) / len(reference)) if reference else None,
        "macro_f1": (sum(v["f1"] for v in scored) / len(scored)) if scored else None,
        "matrix": matrix,
        "columns": columns,
        "per_class": per_class,
        "false_accepts": matrix["not_suitable"]["suitable"],     # reference: not suitable, system: suitable
        "false_rejects": matrix["suitable"]["not_suitable"],     # reference: suitable, system: not suitable
    }


def summarize(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    s = sorted(values)
    mid = len(s) // 2
    median = s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
    return {"n": len(s), "mean": sum(s) / len(s), "median": median, "min": s[0], "max": s[-1]}


def count_by(items: list[str]) -> dict[str, int]:
    return dict(Counter(items))
