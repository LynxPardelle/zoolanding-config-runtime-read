from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RuntimeApiThrottlingTests(unittest.TestCase):
    def test_runtime_bundle_get_has_an_explicit_method_throttle(self):
        template = (ROOT / "template.yaml").read_text(encoding="utf-8")
        runtime_api = template[
            template.index("  RuntimeApi:") : template.index(
                "  ConfigRuntimeReadFunction:"
            )
        ]

        self.assertEqual(1, runtime_api.count("      MethodSettings:"))
        self.assertIn(
            """      MethodSettings:
        - HttpMethod: GET
          ResourcePath: /~1runtime-bundle
          ThrottlingRateLimit: 25
          ThrottlingBurstLimit: 50""",
            runtime_api,
        )
        self.assertNotIn("HttpMethod: '*'", runtime_api)
        self.assertNotIn("ResourcePath: /*", runtime_api)
        self.assertIn("AllowMethods: \"'GET,OPTIONS'\"", runtime_api)


if __name__ == "__main__":
    unittest.main()
