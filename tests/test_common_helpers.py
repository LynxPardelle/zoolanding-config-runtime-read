import io
import json
import unittest
from unittest.mock import patch

import zoolanding_lambda_common as common


class FakeS3:
    def __init__(self, response):
        self.response = response

    def get_object(self, **_kwargs):
        return self.response


class TrackingBody(io.BytesIO):
    def __init__(self, payload):
        super().__init__(payload)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class S3JsonSizeTests(unittest.TestCase):
    def test_rejects_declared_oversized_json_before_reading_body(self):
        body = TrackingBody(b'{}')
        response = {"ContentLength": 1024 * 1024 + 1, "Body": body}

        with patch.object(common, "get_s3_client", return_value=FakeS3(response)):
            with self.assertRaisesRegex(ValueError, "s3_json_too_large"):
                common.load_json_from_s3("bucket", "key")

        self.assertEqual(body.read_sizes, [])

    def test_bounds_body_read_when_content_length_is_missing(self):
        payload = json.dumps({"value": "x" * (1024 * 1024)}).encode("utf-8")
        body = TrackingBody(payload)

        with patch.object(common, "get_s3_client", return_value=FakeS3({"Body": body})):
            with self.assertRaisesRegex(ValueError, "s3_json_too_large"):
                common.load_json_from_s3("bucket", "key")

        self.assertEqual(body.read_sizes, [1024 * 1024 + 1])


if __name__ == "__main__":
    unittest.main()
