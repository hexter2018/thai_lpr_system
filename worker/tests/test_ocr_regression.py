import unittest
from pathlib import Path

from worker.alpr_worker.inference.ocr import PlateOCR


class TestOcrRegression(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_dir = Path(__file__).resolve().parent / "fixtures"
        self.crop_path = self.fixture_dir / "plate_crop.png"
        self.full_frame_path = self.fixture_dir / "20260122_075926156_4_ฆล46_P1.jpg"

    def _fixture_available(self) -> bool:
        return self.crop_path.exists() or self.full_frame_path.exists()

    def test_thai_plate_confusables(self) -> None:
        if not self._fixture_available():
            self.skipTest("Fixture images not available.")

        target_path = self.crop_path if self.crop_path.exists() else self.full_frame_path
        ocr = PlateOCR()
        result = ocr.read_plate(str(target_path))

        self.assertIn("ฆล 46", [result.plate_text] + [c["text"] for c in result.raw.get("plate_candidates", [])])
        province_candidates = [c["name"] for c in result.raw.get("province_candidates", [])]
        self.assertIn("กรุงเทพมหานคร", province_candidates)
        self.assertLess(result.confidence, 1.0)
