"""decode_tx: endpoint URLs, fallback between endpoints, and retry limits.

Bug: the base URLs were joined with "cosmos/tx/v1beta1/decode" without a '/',
so only the first endpoint (which ended in '/') produced a valid URL, and the
loop indexed url_array[retries], raising IndexError once retries passed the
number of endpoints instead of returning None.
"""
import contextlib
import io
import re
import unittest
from unittest import mock

import helpers  # noqa: F401  (puts the repository on sys.path)
import functions
import requests

DECODE_URL = re.compile(r"^https://[^/]+/cosmos/tx/v1beta1/decode$")


def response(status, body=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = body if body is not None else {}
    return r


class DecodeTxTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(functions.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, side_effect, **kwargs):
        with mock.patch.object(functions.requests, "post", side_effect=side_effect) as post, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = functions.decode_tx("dHg=", **kwargs)
        urls = [c.args[0] for c in post.call_args_list]
        return result, urls

    def test_every_endpoint_url_is_well_formed(self):
        down = requests.exceptions.ConnectionError("down")
        _, urls = self.call([down, down, down], max_retries=3)
        self.assertEqual(len(urls), 3)
        self.assertEqual(len(set(urls)), 3, "each retry should try a different endpoint")
        for url in urls:
            self.assertRegex(url, DECODE_URL)

    def test_falls_back_to_next_endpoint(self):
        decoded = {"tx": {"body": {"messages": []}}}
        result, urls = self.call(
            [requests.exceptions.ConnectionError("down"), response(200, decoded)]
        )
        self.assertEqual(result, decoded)
        self.assertEqual(len(urls), 2)
        self.assertNotEqual(urls[0], urls[1])
        self.assertRegex(urls[1], DECODE_URL)

    def test_more_retries_than_endpoints_returns_none(self):
        down = requests.exceptions.ConnectionError("down")
        result, urls = self.call([down] * 10, max_retries=10)
        self.assertIsNone(result)
        self.assertEqual(len(urls), 10)
        self.assertEqual(urls[0], urls[3], "endpoints should be used in rotation")

    def test_rate_limited_response_is_retried(self):
        decoded = {"tx": {}}
        result, urls = self.call([response(429), response(200, decoded)])
        self.assertEqual(result, decoded)
        self.assertEqual(len(urls), 2)

    def test_non_retryable_status_stops(self):
        result, urls = self.call([response(404)])
        self.assertIsNone(result)
        self.assertEqual(len(urls), 1)


if __name__ == "__main__":
    unittest.main()
