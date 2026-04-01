# git-dibs-sdk

If you're reading this, you're already in too deep. Yes, I really made a python sdk for the useless utility that is "Git Dibs". It points at [https://gitdibs.com](https://gitdibs.com) by default.


## Install

```powershell
python -m pip install git-dibs-sdk
```

## Quick Start

```python
from git_dibs_sdk import DibsAlreadyCalledError, GitDibsClient

client = GitDibsClient()

dibs = client.get_dibs("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
if dibs is None:
    print("commit is available")
else:
    print(dibs.reserved_by, dibs.upvote_count)

try:
    created = client.call_dibs(
        commit_hash="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        reserved_by="bb",
    )
    print(created.hash)
except DibsAlreadyCalledError as error:
    print(error)
```

## Client Surface

```python
from git_dibs_sdk import GitDibsClient

client = GitDibsClient(
    base_url="https://gitdibs.com",
    timeout=10.0,
)
```

Available methods:

- `get_dibs(commit_hash: str) -> Dibs | None`
- `call_dibs(commit_hash: str, reserved_by: str) -> Dibs`
- `list_recent_dibs() -> list[Dibs]`
- `list_popular_dibs() -> list[Dibs]`
- `search_dibs(*, query: str | None = None, after: str | None = None, limit: int | None = None) -> DibsSearchResult`
- `upvote_commit(commit_hash: str, voter_fingerprint: str) -> UpvoteResult`

`Dibs` fields:

- `hash: str`
  Full 40-character lowercase SHA-1 commit hash.
  Example: `"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"`
- `reserved_at_utc: str`
  Reservation timestamp in UTC as an ISO 8601 string.
  Example: `"2026-03-28T00:00:00.000Z"`
- `reserved_by: str`
  Alphanumeric caller name recorded by the API.
  Example: `"AndyG"`
- `upvote_count: int`
  Current number of upvotes for the dibs entry.
  Example: `7`

`DibsSearchResult` fields:

- `dibs: list[Dibs]`
  Page of dibs results returned by the search endpoint.
  Example: `[Dibs(...), Dibs(...)]`
- `query: str | None`
  Hex prefix used to filter results, or `None` when listing all dibs.
  Example: `"deadbeef"`
- `after: str | None`
  Full 40-character cursor hash used to continue pagination, or `None` on the first page.
  Example: `"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"`
- `limit: int`
  Maximum number of results requested for the page.
  Example: `10`
- `has_more: bool`
  Whether another page of results exists after this one.
  Example: `True`
- `next_after: str | None`
  Cursor to pass as `after` for the next page, or `None` when there are no more results.
  Example: `"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"`

`UpvoteResult` fields:

- `applied: bool`
  Whether this request added a new upvote rather than hitting an existing deduplicated vote.
  Example: `True`
- `upvote_count: int`
  Current upvote count for the dibs entry after the request.
  Example: `8`

## Error Handling

All transport, HTTP, and response-shape failures are raised as `GitDibsError` subclasses.

- `DibsAlreadyCalledError`: the commit is already reserved
- `GitDibsHttpError`: a non-success HTTP response came back from the API

Example:

```python
from git_dibs_sdk import DibsAlreadyCalledError, GitDibsError, GitDibsClient

client = GitDibsClient()

try:
    client.call_dibs(
        "cccccccccccccccccccccccccccccccccccccccc",
        "TestUser2",
    )
except DibsAlreadyCalledError as error:
    print(error.commit_hash, error.reserved_by)
except GitDibsError as error:
    print(f"request failed: {error}")
```

## API Notes

This SDK matches the current Git Dibs API contract:

- `GET /api/dibs/<commit>`
- `GET /api/dibs/recent`
- `GET /api/dibs/popular`
- `GET /api/dibs/search?q=<optional-prefix>&after=<optional-full-commit>&limit=<optional-1-to-50>`
- `POST /api/dibs`
- `POST /api/upvotes`

Lookup returns `204 No Content` when a commit is available and `200 OK` with a dibs payload when it is reserved.
