#!/usr/bin/env python3
"""Python client for Git Dibs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from json import JSONDecodeError
from typing import Any, Literal, overload
import urllib.error
from urllib.parse import urlencode
import urllib.request


DEFAULT_BASE_URL = "https://gitdibs.com"
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class Dibs:
    hash: str
    reserved_at_utc: str
    reserved_by: str
    upvote_count: int = 0


@dataclass(frozen=True, slots=True)
class DibsSearchResult:
    dibs: list[Dibs]
    query: str | None
    after: str | None
    limit: int
    has_more: bool
    next_after: str | None


@dataclass(frozen=True, slots=True)
class UpvoteResult:
    applied: bool
    upvote_count: int


class GitDibsError(Exception):
    """Base exception for Git Dibs SDK failures."""


class GitDibsHttpError(GitDibsError):
    """Raised when Git Dibs returns a non-success HTTP response."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = dict(payload or {})
        super().__init__(message)


class DibsAlreadyCalledError(GitDibsError):
    def __init__(self, commit_hash: str, reserved_by: str | None) -> None:
        self.commit_hash = commit_hash
        self.reserved_by = reserved_by
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        if self.reserved_by:
            return f"{self.commit_hash} is already reserved by {self.reserved_by}"
        return f"{self.commit_hash} is already reserved"


class GitDibsClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def lookup_commit(self, commit_hash: str) -> Dibs | None:
        payload = self._request_json(
            f"/api/commits/{commit_hash}",
            method="GET",
            allow_no_content=True,
        )
        if payload is None:
            return None
        return _deserialize_dibs_from_container(payload)

    def reserve_commit(self, commit_hash: str, reserved_by: str) -> Dibs:
        try:
            payload = self._request_json(
                "/api/dibs",
                method="POST",
                payload={
                    "commit": commit_hash,
                    "calledBy": reserved_by,
                },
            )
        except GitDibsHttpError as error:
            if error.status_code == 400 and _is_conflict_payload(error.payload):
                dibs = _try_deserialize_embedded_dibs(error.payload)
                if dibs is None:
                    try:
                        dibs = self.lookup_commit(commit_hash)
                    except GitDibsError:
                        dibs = None

                raise DibsAlreadyCalledError(
                    commit_hash=commit_hash,
                    reserved_by=dibs.reserved_by if dibs else None,
                ) from error
            raise

        return _deserialize_dibs_from_container(payload)

    def list_recent_reservations(self) -> list[Dibs]:
        payload = self._request_json("/api/dibs/recent", method="GET")
        return _deserialize_dibs_list_from_container(payload)

    def list_popular_reservations(self) -> list[Dibs]:
        payload = self._request_json("/api/dibs/popular", method="GET")
        return _deserialize_dibs_list_from_container(payload)

    def search_reservations(
        self,
        *,
        query: str | None = None,
        after: str | None = None,
        limit: int | None = None,
    ) -> DibsSearchResult:
        params: dict[str, str | int] = {}
        if query is not None:
            params["q"] = query
        if after is not None:
            params["after"] = after
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be greater than zero")
            params["limit"] = limit

        payload = self._request_json(
            "/api/dibs/search", method="GET", params=params or None
        )
        return _deserialize_search_result(payload)

    def upvote_commit(self, commit_hash: str, voter_fingerprint: str) -> UpvoteResult:
        payload = self._request_json(
            "/api/upvotes",
            method="POST",
            payload={
                "commit": commit_hash,
                "voterFingerprint": voter_fingerprint,
            },
        )
        return _deserialize_upvote_result(payload)

    @overload
    def _request_json(
        self,
        path: str,
        *,
        method: str,
        payload: dict[str, str] | None = None,
        params: dict[str, str | int] | None = None,
        allow_no_content: Literal[True],
    ) -> dict[str, object] | None: ...

    @overload
    def _request_json(
        self,
        path: str,
        *,
        method: str,
        payload: dict[str, str] | None = None,
        params: dict[str, str | int] | None = None,
        allow_no_content: Literal[False] = False,
    ) -> dict[str, object]: ...

    def _request_json(
        self,
        path: str,
        *,
        method: str,
        payload: dict[str, str] | None = None,
        params: dict[str, str | int] | None = None,
        allow_no_content: bool = False,
    ) -> dict[str, object] | None:
        body = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "git-dibs-sdk",
        }

        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        url = f"{self._base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                if allow_no_content and response.status == 204:
                    return None
                try:
                    payload_value = json.load(response)
                except JSONDecodeError as error:
                    raise GitDibsError("Git Dibs returned invalid JSON.") from error
        except urllib.error.HTTPError as error:
            if allow_no_content and error.code == 204:
                return None
            error_payload = _read_error_payload(error)
            message = _build_http_error_message(error.code, error_payload)
            raise GitDibsHttpError(
                error.code, message, payload=error_payload
            ) from error
        except urllib.error.URLError as error:
            reason = getattr(error, "reason", error)
            raise GitDibsError(f"Git Dibs request failed: {reason}") from error
        except OSError as error:
            raise GitDibsError(f"Git Dibs request failed: {error}") from error

        if not isinstance(payload_value, dict):
            raise GitDibsError("Git Dibs returned an unexpected JSON payload.")

        return payload_value


def _deserialize_dibs_from_container(payload: Mapping[str, Any]) -> Dibs:
    dibs_payload = payload.get("dibs")
    if not isinstance(dibs_payload, Mapping):
        raise GitDibsError("Git Dibs response did not include a valid dibs object.")
    return _deserialize_dibs(dibs_payload)


def _deserialize_dibs_list_from_container(payload: Mapping[str, Any]) -> list[Dibs]:
    dibs_payload = payload.get("dibs")
    if not isinstance(dibs_payload, list):
        raise GitDibsError("Git Dibs response did not include a valid dibs list.")
    return [_deserialize_dibs(entry) for entry in dibs_payload]


def _deserialize_dibs(payload: Mapping[str, Any]) -> Dibs:
    if not isinstance(payload, Mapping):
        raise GitDibsError("Git Dibs dibs payload was not an object.")

    try:
        hash_value = str(payload["hash"])
        reserved_at_utc = str(payload["reservedAtUtc"])
        reserved_by = str(payload["reservedBy"])
    except KeyError as error:
        raise GitDibsError(
            f"Git Dibs dibs payload was missing {error.args[0]!r}."
        ) from error

    try:
        upvote_count = int(payload.get("upvoteCount", 0))
    except (TypeError, ValueError) as error:
        raise GitDibsError(
            "Git Dibs dibs payload included an invalid upvoteCount."
        ) from error

    return Dibs(
        hash=hash_value,
        reserved_at_utc=reserved_at_utc,
        reserved_by=reserved_by,
        upvote_count=upvote_count,
    )


def _deserialize_search_result(payload: Mapping[str, Any]) -> DibsSearchResult:
    dibs = _deserialize_dibs_list_from_container(payload)
    try:
        limit = int(payload["limit"])
    except KeyError as error:
        raise GitDibsError("Git Dibs search payload was missing 'limit'.") from error
    except (TypeError, ValueError) as error:
        raise GitDibsError(
            "Git Dibs search payload included an invalid 'limit'."
        ) from error

    has_more = payload.get("hasMore")
    if not isinstance(has_more, bool):
        raise GitDibsError("Git Dibs search payload included an invalid 'hasMore'.")

    return DibsSearchResult(
        dibs=dibs,
        query=_optional_string(payload.get("query")),
        after=_optional_string(payload.get("after")),
        limit=limit,
        has_more=has_more,
        next_after=_optional_string(payload.get("nextAfter")),
    )


def _deserialize_upvote_result(payload: Mapping[str, Any]) -> UpvoteResult:
    applied = payload.get("applied")
    if not isinstance(applied, bool):
        raise GitDibsError("Git Dibs upvote payload included an invalid 'applied'.")

    try:
        upvote_count = int(payload["upvoteCount"])
    except KeyError as error:
        raise GitDibsError(
            "Git Dibs upvote payload was missing 'upvoteCount'."
        ) from error
    except (TypeError, ValueError) as error:
        raise GitDibsError(
            "Git Dibs upvote payload included an invalid 'upvoteCount'."
        ) from error

    return UpvoteResult(applied=applied, upvote_count=upvote_count)


def _read_error_payload(error: urllib.error.HTTPError) -> dict[str, object]:
    try:
        body = error.read().decode("utf-8")
        if not body.strip():
            return {}
        payload = json.loads(body)
    except Exception:
        return {}

    return payload if isinstance(payload, dict) else {}


def _build_http_error_message(status_code: int, payload: Mapping[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message
    return f"Git Dibs request failed with status {status_code}."


def _is_conflict_payload(payload: Mapping[str, Any]) -> bool:
    message = str(payload.get("message", "")).lower()
    details = payload.get("details")
    field = details.get("field") if isinstance(details, Mapping) else None
    return field == "commit" and "already reserved" in message


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise GitDibsError("Git Dibs returned an unexpected JSON payload.")


def _try_deserialize_embedded_dibs(payload: Mapping[str, Any]) -> Dibs | None:
    dibs_payload = payload.get("dibs")
    if not isinstance(dibs_payload, Mapping):
        return None
    try:
        return _deserialize_dibs(dibs_payload)
    except GitDibsError:
        return None
