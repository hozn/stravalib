"""Activity pagination and compatibility checks for the shared iterator."""

import json
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
from pydantic import ValidationError

from stravalib import Client, model
from stravalib.client import BatchedResultsIterator
from stravalib.exc import Fault

API = "https://www.strava.com/api/v3"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("STRAVA_CLIENT_ID", raising=False)
    monkeypatch.delenv("STRAVA_CLIENT_SECRET", raising=False)
    return Client(access_token="offline-test-token", rate_limit_requests=False)


def activities(ids):
    # SummaryActivity accepts id-only objects through normal model validation.
    return [{"id": value} for value in ids]


@contextmanager
def http_pages(path, sequence, *, extra=None):
    """Register finite (page, payload[, status]) expectations, exactly once."""
    trace = []
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:

        def reply(request):
            index = len(trace)
            query = parse_qs(urlsplit(request.url).query)
            trace.append(query)
            assert index < len(sequence), ("Excess request", trace)
            page, payload, *status = sequence[index]
            assert query == {
                "page": [str(page)],
                "per_page": ["200"],
                **{key: [str(value)] for key, value in (extra or {}).items()},
            }, trace
            return (
                status[0] if status else 200,
                {"Content-Type": "application/json"},
                json.dumps(payload),
            )

        http.add_callback(responses.GET, API + path, callback=reply)
        yield http, trace


def assert_activity_result(values, ids, client):
    assert [value.id for value in values] == ids
    assert all(isinstance(value, model.SummaryActivity) for value in values)
    assert all(value.bound_client is client for value in values)


@pytest.mark.parametrize(
    "pages,limit,expected,requested",
    [
        ([[1, 2], [3], []], None, [1, 2, 3], [1, 2, 3]),
        (
            [list(range(1, 201)), [201], [202], []],
            None,
            list(range(1, 203)),
            [1, 2, 3, 4],
        ),
        ([[]], None, [], [1]),
        ([list(range(1, 201)), []], None, list(range(1, 201)), [1, 2]),
        ([[1], []], None, [1], [1, 2]),
        ([list(range(1, 9))], 5, [1, 2, 3, 4, 5], [1]),
        ([list(range(1, 201))], 200, list(range(1, 201)), [1]),
        ([[1, 2], [3, 4, 5, 6]], 5, [1, 2, 3, 4, 5], [1, 2]),
        (
            [list(range(1, 201)), [201, 202, 203]],
            202,
            list(range(1, 203)),
            [1, 2],
        ),
    ],
    ids=[
        "short-first",
        "short-middle",
        "empty-first",
        "full-page-then-empty",
        "empty-terminal-required",
        "limit-inside-page",
        "limit-exact-full-boundary",
        "limit-spans-short-page",
        "limit-spans-full-page",
    ],
)
def test_public_activity_traversal(client, pages, limit, expected, requested):
    sequence = [(page, activities(ids)) for page, ids in enumerate(pages, 1)]
    with http_pages("/athlete/activities", sequence) as (http, trace):
        iterator = client.get_activities(limit=limit)
        assert len(http.calls) == 0
        assert iter(iterator) is iterator
        values = list(iterator)
        assert_activity_result(values, expected, client)
        assert [int(query["page"][0]) for query in trace] == requested
        assert len(http.calls) == len(requested)
        # No more next() calls here: StopIteration intentionally resets the
        # iterator, so subsequent iteration is a new traversal (issue #19).


@pytest.mark.parametrize("first_size", [2, 200], ids=["short", "full"])
def test_partial_consumption_does_not_prefetch(client, first_size):
    sequence = [
        (1, activities(range(1, first_size + 1))),
        (2, activities([first_size + 1])),
        (3, []),
    ]
    with http_pages("/athlete/activities", sequence) as (http, trace):
        iterator = client.get_activities()
        assert not http.calls
        assert next(iterator).id == 1
        assert len(http.calls) == 1
        for expected in range(2, first_size + 1):
            assert next(iterator).id == expected
            assert len(http.calls) == 1
        assert next(iterator).id == first_size + 1
        assert len(http.calls) == 2
        with pytest.raises(StopIteration):
            next(iterator)
        assert len(http.calls) == 3
        assert [query["page"] for query in trace] == [["1"], ["2"], ["3"]]


def test_explicit_reset_discards_buffer_and_restarts_page_one(client):
    sequence = [(1, activities([1, 2])), (1, activities([1, 2])), (2, [])]
    with http_pages("/athlete/activities", sequence) as (http, trace):
        iterator = client.get_activities()
        assert next(iterator).id == 1
        iterator.reset()
        assert len(http.calls) == 1
        assert_activity_result(list(iterator), [1, 2], client)
        assert [query["page"] for query in trace] == [["1"], ["1"], ["2"]]
        assert len(http.calls) == 3


def test_automatic_reset_allows_deliberate_reiteration(client):
    sequence = [(1, activities([1])), (2, []), (1, activities([1])), (2, [])]
    with http_pages("/athlete/activities", sequence) as (http, trace):
        iterator = client.get_activities()
        assert_activity_result(list(iterator), [1], client)
        assert len(http.calls) == 2
        assert_activity_result(list(iterator), [1], client)
        assert len(http.calls) == 4
        assert [query["page"] for query in trace] == [
            ["1"],
            ["2"],
            ["1"],
            ["2"],
        ]


def test_positive_limit_resets_for_deliberate_reiteration(client):
    sequence = [(1, activities(range(1, 9))), (1, activities(range(1, 9)))]
    with http_pages("/athlete/activities", sequence) as (http, trace):
        iterator = client.get_activities(limit=5)
        assert_activity_result(list(iterator), [1, 2, 3, 4, 5], client)
        assert len(http.calls) == 1
        assert_activity_result(list(iterator), [1, 2, 3, 4, 5], client)
        assert len(http.calls) == 2
        assert [query["page"] for query in trace] == [["1"], ["1"]]


def test_query_filters_survive_every_page(client):
    sequence = [(1, activities([1])), (2, activities([2])), (3, [])]
    with http_pages(
        "/athlete/activities",
        sequence,
        extra={"before": 1704240000, "after": 1704067200},
    ) as (http, trace):
        values = list(
            client.get_activities(
                before="2024-01-03T00:00:00Z", after="2024-01-01T00:00:00Z"
            )
        )
        assert_activity_result(values, [1, 2], client)
        assert len(http.calls) == len(trace) == 3


@pytest.mark.parametrize("full_first_page", [False, True])
def test_protocol_errors_propagate(client, full_first_page):
    sequence = []
    if full_first_page:
        sequence.append((1, activities(range(200))))
    sequence.append((len(sequence) + 1, {"message": "Server failure"}, 500))
    with http_pages("/athlete/activities", sequence) as (http, trace):
        iterator = client.get_activities()
        if full_first_page:
            assert [next(iterator).id for _ in range(200)] == list(range(200))
        with pytest.raises(Fault):
            next(iterator)
        assert len(http.calls) == len(trace) == len(sequence)


def test_page_validation_is_not_bypassed_or_partially_yielded(client):
    with http_pages(
        "/athlete/activities", [(1, [{"id": 1}, {"id": "not-an-integer"}])]
    ) as (http, trace):
        iterator = client.get_activities()
        with pytest.raises(ValidationError):
            next(iterator)
        assert len(http.calls) == len(trace) == 1


@pytest.mark.parametrize("activity_policy", [False, True])
@pytest.mark.parametrize("empty_first", [False, True])
def test_iterable_fetcher_materialization(
    client, activity_policy, empty_first
):
    """A generator is truthy even when empty; inspect materialized entities."""
    batches = [[]] if empty_first else [[1, 2], [3], []]
    seen = []

    def fetcher(*, page, per_page):
        assert len(seen) < len(batches), "Unbounded generator fetch"
        assert (page, per_page) == (len(seen) + 1, 2)
        seen.append((page, per_page))
        return ({"id": value} for value in batches[page - 1])

    if activity_policy:
        iterator = client.get_activities()
        iterator.result_fetcher = fetcher
        iterator.per_page = 2
    else:
        iterator = BatchedResultsIterator(
            model.SummaryActivity, fetcher, client, None, 2
        )
    assert not seen
    assert_activity_result(
        list(iterator), [] if empty_first else [1, 2, 3], client
    )
    expected_calls = 1 if empty_first else (3 if activity_policy else 2)
    assert seen == [(page, 2) for page in range(1, expected_calls + 1)]


@pytest.mark.parametrize(
    "method,args,path,extra,payload",
    [
        ("get_athlete_clubs", (), "/athlete/clubs", {}, {"id": 1}),
        ("get_activity_kudos", (42,), "/activities/42/kudos", {}, {"id": 1}),
        ("get_starred_segments", (), "/segments/starred", {}, {"id": 1}),
        ("get_routes", (42,), "/athletes/42/routes", {}, {"id": 1}),
        (
            "get_activity_comments",
            (42,),
            "/activities/42/comments",
            {"markdown": 0},
            {"id": 1},
        ),
        ("get_activity_laps", (42,), "/activities/42/laps", {}, {"id": 1}),
        (
            "get_route_streams",
            (42,),
            "/routes/42/streams",
            {},
            {"type": "distance", "data": [0, 100], "original_size": 2},
        ),
        (
            "list_subscriptions",
            (42, "offline-secret"),
            "/push_subscriptions",
            {"client_id": 42, "client_secret": "offline-secret"},
            {"id": 1},
        ),
        (
            "get_segment_efforts",
            (42,),
            "/segment_efforts",
            {"segment_id": 42},
            {"id": 1},
        ),
        (
            "get_activity_photos",
            (42,),
            "/activities/42/photos",
            {"photo_sources": "true"},
            {"unique_id": "offline-photo"},
        ),
        ("get_athlete_koms", (42,), "/athletes/42/koms", {}, {"id": 1}),
        (
            "get_athlete_starred_segments",
            (42,),
            "/athletes/42/segments/starred",
            {},
            {"id": 1},
        ),
    ],
)
def test_other_consumers_keep_existing_short_page_behavior(
    client, method, args, path, extra, payload
):
    """Other callers still stop after a short page.

    Some endpoints have no documented numbered pagination. If they repeat a
    complete collection for every page, an empty-page rule could loop. The
    one-request budget guards against changing their existing behavior; it
    does not make assumptions about what the live endpoints return.
    """
    with http_pages(path, [(1, [payload])], extra=extra) as (http, trace):
        result = getattr(client, method)(*args)
        if method == "get_route_streams":
            assert set(result) == {"distance"}
            assert isinstance(result["distance"], model.Stream)
        else:
            result = list(result)
            assert len(result) == 1
            key = "unique_id" if method == "get_activity_photos" else "id"
            assert getattr(result[0], key) == payload[key]
        assert len(http.calls) == len(trace) == 1
