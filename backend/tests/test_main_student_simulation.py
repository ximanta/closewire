import importlib.util
import pathlib
import unittest


def _load_main_module():
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    main_path = repo_root / "backend" / "main.py"
    spec = importlib.util.spec_from_file_location("negotiation_main", main_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load backend/main.py for tests")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


main = _load_main_module()


class StudentSimulationParsingTests(unittest.TestCase):
    def test_extract_response_fields_for_student_payload(self):
        text = """
INTERNAL_THOUGHT: He is only talking about modules. My real tension is placement after 2023 passing out.
UPDATED_STATS: {"resistance": 71, "trust": 42, "sentiment": "anxious", "unresolved_concerns": ["Price"]}
MESSAGE: Sir, honestly I am from non-IT background. Placement support for fresher is real or not?
EMOTIONAL_STATE: skeptical
STRATEGIC_INTENT: Validate placement credibility before discussing curriculum.
"""
        parsed = main._extract_response_fields(text)
        self.assertIn("placement", parsed["internal_thought"].lower())
        self.assertEqual(parsed["message"], "Sir, honestly I am from non-IT background. Placement support for fresher is real or not?")
        self.assertEqual(parsed["emotional_state"], "skeptical")
        self.assertEqual(parsed["updated_stats"]["trust"], 42)
        self.assertEqual(parsed["updated_stats"]["resistance"], 71)

    def test_extract_response_fields_for_counsellor_payload(self):
        text = """
MESSAGE: Great question. We support beginners with guided mentoring and weekly mock interviews.
TECHNIQUES_USED: [workload_validation, objection_reframing]
STRATEGIC_INTENT: Reduce anxiety and build trust.
CONFIDENCE_SCORE: 84
"""
        parsed = main._extract_response_fields(text)
        self.assertEqual(parsed["message"], "Great question. We support beginners with guided mentoring and weekly mock interviews.")
        self.assertEqual(parsed["techniques"], ["workload_validation", "objection_reframing"])
        self.assertEqual(parsed["confidence_score"], 84)
        self.assertEqual(parsed["internal_thought"], "")
        self.assertEqual(parsed["updated_stats"], {})

    def test_invalid_updated_state_json_is_ignored(self):
        text = """
INTERNAL_THOUGHT: This sounds too salesy.
UPDATED_STATS: not-a-json
MESSAGE: Can you share refund policy once?
EMOTIONAL_STATE: skeptical
"""
        parsed = main._extract_response_fields(text)
        self.assertEqual(parsed["updated_stats"], {})
        self.assertEqual(parsed["emotional_state"], "skeptical")

    def test_merge_student_inner_state_clamps_values(self):
        current = {
            "sentiment": "curious",
            "skepticism_level": 60,
            "trust_score": 50,
            "unresolved_concerns": ["Price"],
        }
        updates = {"resistance": 130, "trust": -15, "sentiment": "frustrated", "unresolved_concerns": ["Job Guarantee"]}
        merged = main._merge_student_inner_state(current, updates)
        self.assertEqual(merged["skepticism_level"], 100)
        self.assertEqual(merged["trust_score"], 0)
        self.assertEqual(merged["sentiment"], "frustrated")
        self.assertEqual(merged["unresolved_concerns"], ["Job Guarantee"])


if __name__ == "__main__":
    unittest.main()
