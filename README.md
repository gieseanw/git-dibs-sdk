# git-dibs-sdk

If you're reading this, you're already in too deep. Yes, I really made a python sdk for the useless utility that is "Git Dibs". It actually works.


## Install

```powershell
python -m pip install git-dibs-sdk
```

## Quick Start

```python
from git_dibs_sdk import DibsAlreadyCalledError, GitDibsClient

client = GitDibsClient()

dibs = client.lookup_commit("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
if dibs is None:
    print("commit is available")
else:
    print(dibs.reserved_by, dibs.upvote_count)

try:
    created = client.reserve_commit(
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

- `lookup_commit(commit_hash) -> Dibs | None`
- `reserve_commit(commit_hash, reserved_by) -> Dibs`
- `list_recent_reservations() -> list[Dibs]`
- `list_popular_reservations() -> list[Dibs]`
- `search_reservations(query=None, after=None, limit=None) -> DibsSearchResult`
- `upvote_commit(commit_hash, voter_fingerprint) -> UpvoteResult`

`Dibs` fields:

- `hash`
- `reserved_at_utc`
- `reserved_by`
- `upvote_count`

`DibsSearchResult` fields:

- `dibs`
- `query`
- `after`
- `limit`
- `has_more`
- `next_after`

`UpvoteResult` fields:

- `applied`
- `upvote_count`

## Error Handling

All transport, HTTP, and response-shape failures are raised as `GitDibsError` subclasses.

- `DibsAlreadyCalledError`: the commit is already reserved
- `GitDibsHttpError`: a non-success HTTP response came back from the API

Example:

```python
from git_dibs_sdk import DibsAlreadyCalledError, GitDibsError, GitDibsClient

client = GitDibsClient()

try:
    client.reserve_commit(
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

- `GET /api/commits/<commit>`
- `GET /api/dibs/recent`
- `GET /api/dibs/popular`
- `GET /api/dibs/search?q=<optional-prefix>&after=<optional-full-commit>&limit=<optional-1-to-50>`
- `POST /api/dibs`
- `POST /api/upvotes`

Lookup returns `204 No Content` when a commit is available and `200 OK` with a dibs payload when it is reserved.