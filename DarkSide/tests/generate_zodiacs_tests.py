import os
import sys
import unittest
from types import SimpleNamespace, ModuleType
from unittest.mock import MagicMock

# If google.genai is not in this python environment, mock it before importing generate_zodiacs
if "google" not in sys.modules:
    google_mod = ModuleType("google")
    genai_mod = ModuleType("google.genai")
    genai_types = SimpleNamespace(GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs))
    genai_mod.types = genai_types
    genai_mod.Client = MagicMock()
    google_mod.genai = genai_mod
    sys.modules["google"] = google_mod
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = genai_types

if "PIL" not in sys.modules:
    pil_mod = ModuleType("PIL")
    pil_mod.Image = MagicMock()
    sys.modules["PIL"] = pil_mod

# Add Apps directory to path
APPS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Apps"))
if APPS_DIR not in sys.path:
    sys.path.insert(0, APPS_DIR)

import generate_zodiacs

class TestGenerateZodiacs(unittest.TestCase):
    def test_generate_zodiac_image_calls_gemini_flash_image(self):
        fake_client = MagicMock()
        fake_part = SimpleNamespace(inline_data=SimpleNamespace(data=b"FAKE_PNG_BYTES"))
        fake_candidate = SimpleNamespace(content=SimpleNamespace(parts=[fake_part]))
        fake_response = SimpleNamespace(candidates=[fake_candidate])
        fake_client.models.generate_content.return_value = fake_response

        test_zodiac = "TESTDRAGON"
        saved_path = generate_zodiacs.generate_zodiac_image(
            test_zodiac,
            "Festive red paper-cut style",
            api_client=fake_client
        )

        try:
            self.assertTrue(fake_client.models.generate_content.called)
            call_kwargs = fake_client.models.generate_content.call_args.kwargs
            self.assertEqual(call_kwargs["model"], "gemini-3.1-flash-image")
            self.assertIn("holiday_YEAR OF TESTDRAGON.png", saved_path)
            self.assertTrue(os.path.exists(saved_path))
            with open(saved_path, "rb") as f:
                self.assertEqual(f.read(), b"FAKE_PNG_BYTES")
        finally:
            if saved_path and os.path.exists(saved_path):
                os.remove(saved_path)

    def test_generate_zodiac_image_handles_no_image_candidate(self):
        fake_client = MagicMock()
        fake_candidate = SimpleNamespace(content=SimpleNamespace(parts=[]))
        fake_response = SimpleNamespace(candidates=[fake_candidate])
        fake_client.models.generate_content.return_value = fake_response

        saved_path = generate_zodiacs.generate_zodiac_image(
            "TESTEMPTY",
            "Festive style",
            api_client=fake_client
        )
        self.assertIsNone(saved_path)

if __name__ == "__main__":
    unittest.main()
