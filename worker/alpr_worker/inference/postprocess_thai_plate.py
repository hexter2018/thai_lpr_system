from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .provinces import match_province, normalize_province, province_candidates

log = logging.getLogger(__name__)

_THAI_DIGIT_MAP = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_PLATE_CLEAN_RE = re.compile(r"[^0-9ก-ฮ]")
_PLATE_PATTERNS = [
    re.compile(r"^\d[ก-ฮ]{2}\d{3,4}$"),
    re.compile(r"^[ก-ฮ]{2}\d{3,4}$"),
]

_CONFUSABLE_PAIRS = {
    ("ข", "ฆ"),
    ("ฆ", "ข"),
    ("ข", "ม"),
    ("ม", "ข"),
    ("ฆ", "ม"),
    ("ม", "ฆ"),
    ("ผ", "ฆ"),
    ("ฆ", "ผ"),
    ("ร", "ธ"),
    ("ธ", "ร"),
    ("น", "ม"),
    ("ม", "น"),
    ("ฌ", "ณ"),
    ("ณ", "ฌ"),
    ("ต", "ด"),
    ("ด", "ต"),
    ("ถ", "ก"),
    ("ก", "ถ"),
    ("ถ", "ค"),
    ("ค", "ถ"),
    ("ฎ", "ภ"),
    ("ภ", "ฎ"),
    ("ช", "ษ"),
    ("ษ", "ช"),
}


@dataclass
class RerankResult:
    best: Dict[str, object]
    candidates: List[Dict[str, object]]
    margin_ratio: float
    suggestions: List[str]
    flags: List[str]


@dataclass
class ProvinceResolveResult:
    province: str
    score: float
    candidates: List[Dict[str, object]]
    source: str


def normalize_plate_text(text: str) -> str:
    cleaned = (text or "").translate(_THAI_DIGIT_MAP)
    cleaned = re.sub(r"[\s\-_.]", "", cleaned)
    cleaned = _PLATE_CLEAN_RE.sub("", cleaned)
    return cleaned


def plate_pattern_match(text: str) -> bool:
    normalized = normalize_plate_text(text)
    return any(pattern.match(normalized) for pattern in _PLATE_PATTERNS)


def plate_pattern_bonus(text: str) -> float:
    return 0.18 if plate_pattern_match(text) else -0.55


def confusion_aware_distance(a: str, b: str) -> float:
    if a == b:
        return 0.0
    if not a:
        return float(len(b))
    if not b:
        return float(len(a))

    a_norm = normalize_plate_text(a)
    b_norm = normalize_plate_text(b)
    rows = len(a_norm) + 1
    cols = len(b_norm) + 1
    dp = [[0.0 for _ in range(cols)] for _ in range(rows)]

    for i in range(rows):
        dp[i][0] = float(i)
    for j in range(cols):
        dp[0][j] = float(j)

    for i in range(1, rows):
        for j in range(1, cols):
            if a_norm[i - 1] == b_norm[j - 1]:
                cost = 0.0
            elif (a_norm[i - 1], b_norm[j - 1]) in _CONFUSABLE_PAIRS:
                cost = 0.35
            else:
                cost = 1.0
            dp[i][j] = min(
                dp[i - 1][j] + 1.0,
                dp[i][j - 1] + 1.0,
                dp[i - 1][j - 1] + cost,
            )
    return dp[-1][-1]


def _confusable_bonus(text: str, peers: Sequence[str]) -> float:
    best = None
    for other in peers:
        if other == text:
            continue
        dist = confusion_aware_distance(text, other)
        if best is None or dist < best:
            best = dist
    if best is None:
        return 0.0
    if best <= 1.0:
        return 0.08
    if best <= 1.5:
        return 0.04
    return 0.0


def rerank_plate_candidates(
    candidates: Sequence[Dict[str, object]],
    *,
    variant_count: int,
    margin_min: float,
    consensus_min: float,
) -> RerankResult:
    if not candidates:
        return RerankResult(
            best={"text": "", "final_score": 0.0, "avg_conf": 0.0, "consensus_ratio": 0.0, "count": 0},
            candidates=[],
            margin_ratio=0.0,
            suggestions=[],
            flags=["empty_candidates"],
        )

    max_score = max(float(c.get("score", 0.0)) for c in candidates) or 1.0
    variant_count = max(variant_count, 1)
    peers = [normalize_plate_text(str(c.get("text", ""))) for c in candidates]

    def build_scores(consensus_weight: float, pattern_weight: float) -> List[Dict[str, object]]:
        scored: List[Dict[str, object]] = []
        for cand in candidates:
            text = normalize_plate_text(str(cand.get("text", "")))
            avg_conf = float(cand.get("avg_conf", 0.0))
            consensus_ratio = float(cand.get("consensus_ratio", 0.0))
            count_ratio = float(cand.get("count", 0)) / variant_count
            score_ratio = float(cand.get("score", 0.0)) / max_score
            base_score = (0.45 * avg_conf) + (consensus_weight * consensus_ratio) + (0.2 * count_ratio)
            final = base_score + (0.15 * score_ratio) + (pattern_weight * (1.0 if plate_pattern_match(text) else -1.0))
            final += _confusable_bonus(text, peers)
            scored.append({
                "text": text,
                "avg_conf": avg_conf,
                "consensus_ratio": consensus_ratio,
                "count": int(cand.get("count", 0)),
                "score": float(cand.get("score", 0.0)),
                "final_score": float(final),
                "pattern_match": plate_pattern_match(text),
            })
        scored.sort(key=lambda item: item["final_score"], reverse=True)
        return scored

    scored = build_scores(consensus_weight=0.35, pattern_weight=0.18)
    best = scored[0]
    second = scored[1] if len(scored) > 1 else None
    margin_ratio = 1.0
    if second and best["final_score"]:
        margin_ratio = (best["final_score"] - second["final_score"]) / max(best["final_score"], 1e-6)

    flags: List[str] = []
    if best["consensus_ratio"] < consensus_min:
        flags.append("low_consensus")
    if margin_ratio < margin_min:
        flags.append("tight_margin")

    if "tight_margin" in flags:
        scored = build_scores(consensus_weight=0.45, pattern_weight=0.25)
        best = scored[0]
        second = scored[1] if len(scored) > 1 else None
        if second and best["final_score"]:
            margin_ratio = (best["final_score"] - second["final_score"]) / max(best["final_score"], 1e-6)

    if best["avg_conf"] < 0.6:
        flags.append("low_confidence")

    suggestions: List[str] = []
    if margin_ratio < (margin_min * 0.8):
        suggestions = [cand["text"] for cand in scored[:3]]

    return RerankResult(
        best=best,
        candidates=scored,
        margin_ratio=float(max(0.0, margin_ratio)),
        suggestions=suggestions,
        flags=flags,
    )


def resolve_province(
    *,
    line_texts: Sequence[str],
    roi_province: Dict[str, object],
    fallback_candidates: Sequence[Dict[str, object]],
    min_score: float,
    prior: Optional[Dict[str, float]] = None,
) -> ProvinceResolveResult:
    candidates: Dict[str, float] = {}

    for text in line_texts:
        for name, score in province_candidates(text, limit=3, threshold=int(min_score)):
            if name and score > candidates.get(name, 0.0):
                candidates[name] = float(score)

    roi_name = str(roi_province.get("province") or "")
    roi_score = float(roi_province.get("score") or 0.0)
    if roi_name:
        candidates[roi_name] = max(candidates.get(roi_name, 0.0), roi_score)

    resolved = [
        {"name": name, "score": score}
        for name, score in sorted(candidates.items(), key=lambda item: item[1], reverse=True)
    ]

    if prior and len(resolved) > 1:
        top = resolved[0]
        runner_up = resolved[1]
        if (top["score"] - runner_up["score"]) <= 2.0:
            for item in resolved:
                if item["name"] in prior:
                    item["score"] += float(prior[item["name"]])
            resolved.sort(key=lambda item: item["score"], reverse=True)

    if resolved and resolved[0]["score"] >= min_score:
        chosen = resolved[0]
        return ProvinceResolveResult(
            province=normalize_province(str(chosen["name"]), threshold=int(min_score)),
            score=float(chosen["score"]),
            candidates=resolved,
            source="roi_line",
        )

    fallback_map: Dict[str, float] = {}
    for item in fallback_candidates:
        name = str(item.get("name") or "")
        score = float(item.get("score") or 0.0)
        if not name:
            continue
        fallback_map[name] = max(fallback_map.get(name, 0.0), score)

    fallback_list = [
        {"name": name, "score": score}
        for name, score in sorted(fallback_map.items(), key=lambda item: item[1], reverse=True)
    ]
    if fallback_list and fallback_list[0]["score"] >= min_score:
        chosen = fallback_list[0]
        return ProvinceResolveResult(
            province=normalize_province(str(chosen["name"]), threshold=int(min_score)),
            score=float(chosen["score"]),
            candidates=fallback_list,
            source="fallback",
        )

    return ProvinceResolveResult(
        province="",
        score=0.0,
        candidates=resolved or fallback_list,
        source="none",
    )


def load_province_prior(raw: str) -> Dict[str, float]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Invalid OCR_PROVINCE_PRIOR JSON; skipping.")
        return {}
    if not isinstance(data, dict):
        return {}
    cleaned: Dict[str, float] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        try:
            cleaned[key] = float(value)
        except (TypeError, ValueError):
            continue
    return cleaned
