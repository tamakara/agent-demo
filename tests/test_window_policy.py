import unittest

from app.window_policy import WindowThresholds


class WindowPolicyTests(unittest.TestCase):
    def test_summary_and_notebook_limits_are_derived_from_ratios(self) -> None:
        thresholds = WindowThresholds.from_total_limit(
            200_000,
            memory_capacity_ratio=0.10,
            notebook_capacity_ratio=0.04,
            dialogue_summary_ratio=0.05,
            retention_ratio=0.10,
        )
        self.assertEqual(thresholds.summary_token_limit, 10_000)
        self.assertEqual(thresholds.notebook_total_token_limit, 8_000)
        self.assertEqual(thresholds.system_prompt_limit, 40_000)
        self.assertEqual(thresholds.resident_limit, thresholds.system_prompt_limit + thresholds.retention_limit)


if __name__ == "__main__":
    unittest.main()
