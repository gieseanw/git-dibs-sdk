from __future__ import annotations

from email.message import Message
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
import urllib.error


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from git_dibs_sdk import (  # noqa: E402
    DibsAlreadyCalledError,
    GitDibsClient,
    GitDibsError,
    GitDibsHttpError,
)


class MockJsonResponse(io.BytesIO):
    def __init__(self, payload: object, *, status: int = 200) -> None:
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.status = status


class MockNoContentResponse(io.BytesIO):
    def __init__(self) -> None:
        super().__init__(b"")
        self.status = 204


def make_http_error(status_code: int, payload: object) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://example.com/api/test",
        code=status_code,
        msg="error",
        hdrs=Message(),
        fp=io.BytesIO(json.dumps(payload).encode("utf-8")),
    )


class GitDibsClientTests(unittest.TestCase):
    def test_lookup_commit_returns_none_on_no_content(self) -> None:
        client = GitDibsClient("https://example.com")

        with mock.patch("urllib.request.urlopen", return_value=MockNoContentResponse()):
            self.assertIsNone(client.lookup_commit("a" * 40))

    def test_lookup_commit_uses_configured_timeout(self) -> None:
        client = GitDibsClient("https://example.com", timeout=3.5)

        with mock.patch(
            "urllib.request.urlopen",
            return_value=MockJsonResponse(
                {
                    "dibs": {
                        "hash": "a" * 40,
                        "reservedAtUtc": "2026-03-28T00:00:00.000Z",
                        "reservedBy": "Alice",
                        "upvoteCount": 4,
                    }
                }
            ),
        ) as mocked_urlopen:
            client.lookup_commit("a" * 40)

        self.assertEqual(mocked_urlopen.call_args.kwargs["timeout"], 3.5)

    def test_lookup_commit_wraps_url_errors(self) -> None:
        client = GitDibsClient("https://example.com")

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            with self.assertRaisesRegex(GitDibsError, "offline"):
                client.lookup_commit("a" * 40)

    def test_lookup_commit_wraps_invalid_response_shapes(self) -> None:
        client = GitDibsClient("https://example.com")

        with mock.patch(
            "urllib.request.urlopen",
            return_value=MockJsonResponse({"unexpected": {}}),
        ):
            with self.assertRaisesRegex(GitDibsError, "dibs object"):
                client.lookup_commit("a" * 40)

    def test_lookup_commit_raises_http_error_with_payload(self) -> None:
        client = GitDibsClient("https://example.com")

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=make_http_error(
                400,
                {
                    "message": "Commit lookup requires a full 40-character hexadecimal commit ID.",
                    "details": {"field": "commit"},
                },
            ),
        ):
            with self.assertRaises(GitDibsHttpError) as raised:
                client.lookup_commit("not-a-hash")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.payload["details"], {"field": "commit"})

    def test_reserve_commit_conflict_survives_lookup_failure(self) -> None:
        client = GitDibsClient("https://example.com")

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=[
                make_http_error(
                    400,
                    {
                        "message": "That commit is already reserved.",
                        "details": {"field": "commit"},
                    },
                ),
                urllib.error.URLError("lookup offline"),
            ],
        ):
            with self.assertRaises(DibsAlreadyCalledError) as raised:
                client.reserve_commit("a" * 40, "Alice")

        self.assertEqual(raised.exception.commit_hash, "a" * 40)
        self.assertIsNone(raised.exception.reserved_by)

    def test_reserve_commit_prefers_embedded_dibs_on_conflict(self) -> None:
        client = GitDibsClient("https://example.com")

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=make_http_error(
                400,
                {
                    "message": "That commit is already reserved.",
                    "details": {"field": "commit"},
                    "dibs": {
                        "hash": "a" * 40,
                        "reservedAtUtc": "2026-03-28T00:00:00.000Z",
                        "reservedBy": "Alice",
                        "upvoteCount": 9,
                    },
                },
            ),
        ) as mocked_urlopen:
            with self.assertRaises(DibsAlreadyCalledError) as raised:
                client.reserve_commit("a" * 40, "Bob")

        self.assertEqual(raised.exception.reserved_by, "Alice")
        self.assertEqual(mocked_urlopen.call_count, 1)

    def test_list_recent_reservations_parses_dibs(self) -> None:
        client = GitDibsClient("https://example.com")

        with mock.patch(
            "urllib.request.urlopen",
            return_value=MockJsonResponse(
                {
                    "dibs": [
                        {
                            "hash": "a" * 40,
                            "reservedAtUtc": "2026-03-28T00:00:00.000Z",
                            "reservedBy": "Alice",
                            "upvoteCount": 2,
                        }
                    ]
                }
            ),
        ):
            dibs = client.list_recent_reservations()

        self.assertEqual(len(dibs), 1)
        self.assertEqual(dibs[0].upvote_count, 2)

    def test_search_reservations_parses_page(self) -> None:
        client = GitDibsClient("https://example.com")

        with mock.patch(
            "urllib.request.urlopen",
            return_value=MockJsonResponse(
                {
                    "dibs": [
                        {
                            "hash": "a" * 40,
                            "reservedAtUtc": "2026-03-28T00:00:00.000Z",
                            "reservedBy": "Alice",
                            "upvoteCount": 5,
                        }
                    ],
                    "query": "aaaa",
                    "after": "a" * 40,
                    "limit": 10,
                    "hasMore": True,
                    "nextAfter": "b" * 40,
                }
            ),
        ) as mocked_urlopen:
            page = client.search_reservations(query="aaaa", after="a" * 40, limit=10)

        request = mocked_urlopen.call_args.args[0]
        self.assertIn("q=aaaa", request.full_url)
        self.assertIn("limit=10", request.full_url)
        self.assertTrue(page.has_more)
        self.assertEqual(page.next_after, "b" * 40)

    def test_upvote_commit_parses_result(self) -> None:
        client = GitDibsClient("https://example.com")

        with mock.patch(
            "urllib.request.urlopen",
            return_value=MockJsonResponse({"applied": True, "upvoteCount": 7}),
        ):
            result = client.upvote_commit("a" * 40, "browser-fingerprint")

        self.assertTrue(result.applied)
        self.assertEqual(result.upvote_count, 7)


if __name__ == "__main__":
    unittest.main()
