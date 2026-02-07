import unittest

from worker.alpr_worker.inference.postprocess_thai_plate import (
    normalize_plate_text,
    rerank_plate_candidates,
    resolve_province,
)


def _make_candidate(text: str, avg_conf: float, count: int, consensus: float, score: float) -> dict:
    return {
        "text": text,
        "avg_conf": avg_conf,
        "count": count,
        "consensus_ratio": consensus,
        "score": score,
    }


GROUND_TRUTH_CASES = [
    {"plate": "กธ278", "province": "แพร่"},
    {"plate": "8กน6228", "province": "กรุงเทพมหานคร"},
    {"plate": "ฌฌ137", "province": "กรุงเทพมหานคร"},
    {"plate": "กต9639", "province": "กรุงเทพมหานคร"},
    {"plate": "8กย141", "province": "กรุงเทพมหานคร"},
    {"plate": "กก1234", "province": "นนทบุรี"},
    {"plate": "6ขถ3821", "province": "กรุงเทพมหานคร"},
    {"plate": "ฎช3078", "province": "กรุงเทพมหานคร"},
    {"plate": "6กท889", "province": "กรุงเทพมหานคร"},
    {"plate": "5ขช567", "province": "กรุงเทพมหานคร"},
    {"plate": "ฬจ7777", "province": "กรุงเทพมหานคร"},
    {"plate": "2ฒธ1881", "province": "กรุงเทพมหานคร"},
    {"plate": "สฐ5771", "province": "กรุงเทพมหานคร"},
    {"plate": "ฌค1268", "province": "กรุงเทพมหานคร"},
    {"plate": "ฆช2800", "province": "กรุงเทพมหานคร"},
    {"plate": "ขฬ5801", "province": "กรุงเทพมหานคร"},
    {"plate": "6ขง1307", "province": "กรุงเทพมหานคร"},
]


PLATE_CANDIDATE_FIXTURES = {
    "กธ278": [
        _make_candidate("กธ 278", 0.68, 3, 0.62, 1.08),
        _make_candidate("กร278", 0.74, 1, 0.22, 1.12),
        _make_candidate("กน278", 0.62, 1, 0.18, 0.95),
    ],
    "8กน6228": [
        _make_candidate("8กน6228", 0.72, 4, 0.72, 1.28),
        _make_candidate("8กม6228", 0.73, 1, 0.2, 1.2),
        _make_candidate("8กว6228", 0.6, 1, 0.2, 0.95),
    ],
    "ฌฌ137": [
        _make_candidate("ฌฌ137", 0.65, 3, 0.6, 1.02),
        _make_candidate("ณฌ137", 0.7, 1, 0.2, 1.08),
        _make_candidate("ฌณ137", 0.68, 1, 0.25, 1.04),
    ],
    "กต9639": [
        _make_candidate("กต9639", 0.69, 3, 0.64, 1.1),
        _make_candidate("กด9639", 0.71, 1, 0.2, 1.09),
        _make_candidate("กถ9639", 0.6, 1, 0.2, 0.98),
    ],
    "8กย141": [
        _make_candidate("8กย141", 0.7, 3, 0.66, 1.12),
        _make_candidate("8กบ141", 0.74, 1, 0.2, 1.1),
        _make_candidate("8กน141", 0.63, 1, 0.18, 0.96),
    ],
    "กก1234": [
        _make_candidate("กก1234", 0.7, 4, 0.72, 1.25),
        _make_candidate("กถ1234", 0.76, 1, 0.2, 1.18),
        _make_candidate("ถก1234", 0.6, 1, 0.2, 0.94),
    ],
    "6ขถ3821": [
        _make_candidate("6ขถ3821", 0.71, 3, 0.64, 1.14),
        _make_candidate("6ขก3821", 0.75, 1, 0.22, 1.15),
        _make_candidate("6ขค3821", 0.68, 1, 0.2, 1.03),
    ],
    "ฎช3078": [
        _make_candidate("ฎช3078", 0.67, 3, 0.6, 1.05),
        _make_candidate("ภช3078", 0.74, 1, 0.2, 1.09),
        _make_candidate("ฎษ3078", 0.64, 1, 0.2, 0.98),
    ],
    "6กท889": [
        _make_candidate("6กท889", 0.69, 3, 0.62, 1.1),
        _make_candidate("6กธ889", 0.73, 1, 0.2, 1.12),
        _make_candidate("6กถ889", 0.65, 1, 0.2, 0.97),
    ],
    "5ขช567": [
        _make_candidate("5ขช567", 0.7, 3, 0.65, 1.12),
        _make_candidate("5ขษ567", 0.72, 1, 0.2, 1.11),
        _make_candidate("5ขซ567", 0.62, 1, 0.2, 0.94),
    ],
    "ฬจ7777": [
        _make_candidate("ฬจ7777", 0.72, 3, 0.7, 1.2),
        _make_candidate("ฝจ7777", 0.75, 1, 0.2, 1.1),
        _make_candidate("ฬฉ7777", 0.6, 1, 0.2, 0.92),
    ],
    "2ฒธ1881": [
        _make_candidate("2ฒธ1881", 0.68, 3, 0.62, 1.08),
        _make_candidate("2ฒร1881", 0.72, 1, 0.2, 1.1),
        _make_candidate("2ฒถ1881", 0.61, 1, 0.2, 0.94),
    ],
    "สฐ5771": [
        _make_candidate("สฐ5771", 0.69, 3, 0.64, 1.1),
        _make_candidate("สถ5771", 0.74, 1, 0.2, 1.12),
        _make_candidate("สก5771", 0.6, 1, 0.18, 0.93),
    ],
    "ฌค1268": [
        _make_candidate("ฌค1268", 0.7, 3, 0.66, 1.12),
        _make_candidate("ฌถ1268", 0.72, 1, 0.2, 1.11),
        _make_candidate("ณค1268", 0.68, 1, 0.2, 1.03),
    ],
    "ฆช2800": [
        _make_candidate("ฆช2800", 0.69, 3, 0.64, 1.1),
        _make_candidate("ขช2800", 0.74, 1, 0.2, 1.12),
        _make_candidate("ฆษ2800", 0.63, 1, 0.2, 0.96),
    ],
    "ขฬ5801": [
        _make_candidate("ขฬ5801", 0.7, 3, 0.66, 1.12),
        _make_candidate("ฆฬ5801", 0.74, 1, 0.2, 1.12),
        _make_candidate("ขล5801", 0.6, 1, 0.18, 0.92),
    ],
    "6ขง1307": [
        _make_candidate("6ขง1307", 0.7, 3, 0.66, 1.12),
        _make_candidate("6ฆง1307", 0.73, 1, 0.2, 1.11),
        _make_candidate("6ขม1307", 0.62, 1, 0.18, 0.94),
    ],
}


PROVINCE_FIXTURES = {
    "แพร่": {"line_texts": ["แพร่", "พร่"], "fallback": []},
    "กรุงเทพมหานคร": {"line_texts": ["กรงเทพมหานคร", "กทม"], "fallback": []},
    "นนทบุรี": {"line_texts": [], "fallback": [{"name": "นนทบุรี", "score": 78.0}]},
}


class TestPostprocessThaiPlate(unittest.TestCase):
    def test_normalize_plate_text(self) -> None:
        self.assertEqual(normalize_plate_text("8กน 6228"), "8กน6228")
        self.assertEqual(normalize_plate_text("ก-ต.9639"), "กต9639")

    def test_plate_rerank_and_province_resolution(self) -> None:
        total = len(GROUND_TRUTH_CASES)
        plate_hits_before = 0
        plate_hits_after = 0
        province_hits = 0
        low_conf_before = 0
        low_conf_after = 0

        for case in GROUND_TRUTH_CASES:
            plate = case["plate"]
            province = case["province"]
            candidates = PLATE_CANDIDATE_FIXTURES[plate]

            before = max(candidates, key=lambda c: c["score"])
            if normalize_plate_text(before["text"]) == plate:
                plate_hits_before += 1
            if before["avg_conf"] < 0.6 or before["consensus_ratio"] < 0.55:
                low_conf_before += 1

            result = rerank_plate_candidates(
                candidates,
                variant_count=5,
                margin_min=0.16,
                consensus_min=0.55,
            )
            if result.best["text"] == plate:
                plate_hits_after += 1
            if "low_confidence" in result.flags or "low_consensus" in result.flags:
                low_conf_after += 1

            province_fixture = PROVINCE_FIXTURES.get(province, PROVINCE_FIXTURES["กรุงเทพมหานคร"])
            province_result = resolve_province(
                line_texts=province_fixture["line_texts"],
                roi_province={"province": province, "score": 82.0},
                fallback_candidates=province_fixture["fallback"],
                min_score=65.0,
                prior=None,
            )
            if province_result.province == province:
                province_hits += 1

        print("Plate accuracy before:", plate_hits_before / total)
        print("Plate accuracy after:", plate_hits_after / total)
        print("Province accuracy:", province_hits / total)
        print("Low confidence before:", low_conf_before)
        print("Low confidence after:", low_conf_after)

        self.assertEqual(plate_hits_after, total)
        self.assertEqual(province_hits, total)
