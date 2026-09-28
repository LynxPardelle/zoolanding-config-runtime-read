import importlib
import unittest
from unittest.mock import patch


class ProtectedRuntimeEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.handler = importlib.import_module("lambda_function")

    def site(self, origin="https://admin.thehairnarrative.com"):
        return {"domain": "thehairnarrative.com", "runtime": {"authRemote": {
            "enabled": True, "authProfileId": "journal-owner", "endpoint": "/auth-v2/runtime-config", "requiredOrigin": origin}}}

    def test_production_thn_runtime_requires_server_environment_and_exact_origin(self):
        validate = getattr(self.handler, "_validate_thn_protected_runtime", None)
        self.assertTrue(callable(validate), "THN production runtime has no server environment guard")
        with patch.dict("os.environ", {"ENVIRONMENT_NAME": "prod"}, clear=True):
            validate(self.site(), "production")
            for environment, origin in (("test", "https://admin.thehairnarrative.com"),
                                       ("production", "https://admin-test.thehairnarrative.com"),
                                       ("production", "https://other.example.com")):
                with self.subTest(environment=environment, origin=origin), self.assertRaises(ValueError):
                    validate(self.site(origin), environment)
        for server_environment in ("", "test", "main", "live"):
            with patch.dict("os.environ", {"ENVIRONMENT_NAME": server_environment}, clear=True), self.assertRaises(ValueError):
                validate(self.site(), "production")


    def test_private_endpoint_cannot_bypass_profile_guard_by_mutating_profile(self):
        site = self.site()
        site["runtime"]["authRemote"]["authProfileId"] = "other-profile"
        with patch.dict("os.environ", {"ENVIRONMENT_NAME": "prod"}, clear=True), self.assertRaises(ValueError):
            self.handler._validate_thn_protected_runtime(site, "production")
        legacy = self.site()
        legacy["runtime"]["authRemote"].update(authProfileId="legacy-owner", endpoint="/auth/runtime-config")
        with patch.dict("os.environ", {}, clear=True):
            self.handler._validate_thn_protected_runtime(legacy, "production")
