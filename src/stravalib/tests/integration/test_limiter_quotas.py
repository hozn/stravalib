"""Offline public-client checks for independent Strava quota families."""

import json
import os
from io import BytesIO
from unittest.mock import Mock, patch

import arrow
import pytest
import responses

from stravalib import Client, exc
from stravalib.client import ActivityUploader
from stravalib.util import limiter

NOW = arrow.get("2026-10-28T12:05:00Z")
SHORT = 599
LONG = 42899
BASE = {
    "X-RateLimit-Usage": "100,1000",
    "X-RateLimit-Limit": "200,10000",
    "X-ReadRateLimit-Usage": "30,300",
    "X-ReadRateLimit-Limit": "100,5000",
}
OPERATIONS = {
    "athlete": ("GET", "/athlete"),
    "subscription": ("POST", "/push_subscriptions"),
    "update": ("PUT", "/activities/1"),
    "delete": ("DELETE", "/push_subscriptions/1"),
    "create": ("POST", "/activities"),
    "upload": ("POST", "/uploads"),
    "upload_status": ("GET", "/uploads/1"),
}


def invoke(client, operation):
    if operation == "athlete":
        return client.get_athlete()
    if operation == "subscription":
        return client.create_subscription(123, "fake", "https://example.test")
    if operation == "update":
        return client.update_activity(1, name="offline test")
    if operation == "delete":
        return client.delete_subscription(1, 123, "fake")
    if operation == "create":
        return client.create_activity(
            "offline test", "2026-10-28T12:00:00Z", 60, sport_type="Run"
        )
    if operation == "upload":
        return client.upload_activity(BytesIO(b"<gpx/>"), data_type="gpx")
    if operation == "upload_status":
        return ActivityUploader(client, response={"id": 1}).poll()
    raise AssertionError(operation)


def observe(
    operation, headers, priority="high", status=200, custom=None, api_base=None
):
    method, path = OPERATIONS[operation]
    events = []
    evaluated_rates = []
    get_wait_time = limiter.SleepingRateLimitRule._get_wait_time

    def record_wait(rule, rates, short_reset, long_reset):
        evaluated_rates.append(rates._asdict())
        return get_wait_time(rule, rates, short_reset, long_reset)

    with patch.dict(
        os.environ, {"SILENCE_TOKEN_WARNINGS": "true"}, clear=True
    ):
        rate_limiter = custom or limiter.DefaultRateLimiter(priority)
        client = Client(rate_limiter=rate_limiter)
        if api_base is not None:
            client.protocol.api_base = api_base

    def response(request):
        events.append("http")
        body = {"id": 1}
        if status >= 400:
            body = {"message": "Rate Limit Exceeded", "errors": []}
        return status, headers, "" if status == 204 else json.dumps(body)

    def sleep(seconds):
        events.append(["sleep", seconds])

    error = None
    with (
        responses.RequestsMock() as http,
        patch("stravalib.util.limiter.arrow.utcnow", return_value=NOW),
        patch("stravalib.util.limiter.time.sleep", side_effect=sleep),
        patch.object(
            limiter.SleepingRateLimitRule, "_get_wait_time", record_wait
        ),
    ):
        http.add_callback(method, client.protocol.resolve_url(path), response)
        try:
            invoke(client, operation)
        except (exc.Fault, KeyError) as caught:
            error = type(caught).__name__
            events.append(["error", error])
        else:
            events.append("return")
        requests = [(c.request.method, c.request.url) for c in http.calls]
    try:
        parsed = limiter.get_rates_from_response_headers(headers, method)
    except KeyError as caught:
        parsed = f"KeyError({caught})"
    return {
        "operation": operation,
        "headers": headers,
        "priority": priority,
        "status": status,
        "legacy_parser": parsed,
        "evaluated_rates": evaluated_rates,
        "requests": requests,
        "events": events,
        "sleeps": [
            x[1] for x in events if isinstance(x, list) and x[0] == "sleep"
        ],
        "error": error,
    }


# Expected waits preserve the existing reset helpers, including their rounding.
CASES = [
    (
        "A-overall-short",
        "athlete",
        {"X-RateLimit-Usage": "200,1000"},
        "high",
        SHORT,
    ),
    (
        "B-non-upload-post",
        "subscription",
        {"X-ReadRateLimit-Usage": "100,300"},
        "high",
        SHORT,
    ),
    (
        "B-non-upload-put",
        "update",
        {"X-ReadRateLimit-Usage": "100,300"},
        "high",
        SHORT,
    ),
    (
        "B-non-upload-delete",
        "delete",
        {"X-ReadRateLimit-Usage": "100,300"},
        "high",
        SHORT,
    ),
    (
        "C-exempt-create",
        "create",
        {"X-ReadRateLimit-Usage": "100,5000", "X-RateLimit-Usage": "100,6000"},
        "high",
        0,
    ),
    (
        "C-exempt-upload",
        "upload",
        {"X-ReadRateLimit-Usage": "100,5000", "X-RateLimit-Usage": "100,6000"},
        "high",
        0,
    ),
    (
        "C-upload-overall",
        "upload",
        {"X-RateLimit-Usage": "200,1000"},
        "high",
        SHORT,
    ),
    (
        "C-upload-status-is-not-exempt",
        "upload_status",
        {"X-ReadRateLimit-Usage": "100,300"},
        "high",
        SHORT,
    ),
    (
        "C-upload-status-overall",
        "upload_status",
        {"X-RateLimit-Usage": "200,1000"},
        "high",
        SHORT,
    ),
    ("D-high", "athlete", {}, "high", 0),
    ("D-medium-read-tight", "athlete", {}, "medium", SHORT / 70),
    (
        "D-medium-overall-tight",
        "athlete",
        {"X-RateLimit-Usage": "199,1000"},
        "medium",
        SHORT,
    ),
    ("D-low-read-tight", "athlete", {}, "low", LONG / 4700),
    (
        "D-low-overall-tight",
        "athlete",
        {"X-RateLimit-Usage": "100,9999"},
        "low",
        LONG,
    ),
    (
        "D-medium-daily-half",
        "athlete",
        {"X-RateLimit-Usage": "100,9999"},
        "medium",
        LONG,
    ),
    (
        "D-ratio-is-not-remaining-capacity",
        "athlete",
        {
            "X-RateLimit-Usage": "995,1000",
            "X-RateLimit-Limit": "1000,10000",
            "X-ReadRateLimit-Usage": "99,300",
        },
        "medium",
        SHORT,
    ),
    ("D-medium-post", "subscription", {}, "medium", SHORT / 70),
    ("D-low-post", "subscription", {}, "low", LONG / 4700),
    ("D-low-exempt", "upload", {}, "low", SHORT / 100),
    (
        "E-overall-daily",
        "athlete",
        {"X-RateLimit-Usage": "100,10000"},
        "high",
        LONG,
    ),
    (
        "E-read-short",
        "athlete",
        {"X-ReadRateLimit-Usage": "100,300"},
        "high",
        SHORT,
    ),
    (
        "E-read-daily",
        "athlete",
        {"X-ReadRateLimit-Usage": "30,5000", "X-RateLimit-Usage": "100,6000"},
        "high",
        LONG,
    ),
    (
        "E-overall-short-read-daily",
        "athlete",
        {"X-RateLimit-Usage": "200,5000", "X-ReadRateLimit-Usage": "30,5000"},
        "high",
        LONG,
    ),
    (
        "E-overall-daily-read-short",
        "athlete",
        {"X-RateLimit-Usage": "100,10000", "X-ReadRateLimit-Usage": "100,300"},
        "high",
        LONG,
    ),
    (
        "E-post-read-daily",
        "subscription",
        {"X-ReadRateLimit-Usage": "30,5000", "X-RateLimit-Usage": "100,5000"},
        "high",
        LONG,
    ),
]


@pytest.mark.parametrize(
    "name,operation,updates,priority,expected",
    CASES,
    ids=[c[0] for c in CASES],
)
def test_applicable_quotas(name, operation, updates, priority, expected):
    observed = observe(operation, BASE | updates, priority)
    assert observed["error"] is None, observed
    assert len(observed["requests"]) == 1
    assert observed["sleeps"] == [pytest.approx(expected)], observed
    assert observed["events"][0] == "http"
    assert observed["events"][-1] == "return"


@pytest.mark.parametrize("casing", (str.lower, str.upper, str.swapcase))
def test_case_insensitive_dual_quotas(casing):
    headers = {
        casing(k): v
        for k, v in (BASE | {"X-RateLimit-Usage": "200,1000"}).items()
    }
    observed = observe("athlete", headers)
    assert observed["sleeps"] == [SHORT], observed


@pytest.mark.parametrize("family", ("RateLimit", "ReadRateLimit"))
def test_single_family(family):
    headers = {f"X-{family}-Usage": "100,300", f"X-{family}-Limit": "100,5000"}
    assert observe("athlete", headers)["sleeps"] == [SHORT]


@pytest.mark.parametrize("headers", ({}, {"X-RateLimit-Limit": "200,10000"}))
def test_no_usage_headers(headers):
    observed = observe("athlete", headers)
    assert observed["legacy_parser"] is None
    assert observed["sleeps"] == []
    assert observed["error"] is None


@pytest.mark.parametrize("family", ("RateLimit", "ReadRateLimit"))
def test_usage_without_limit_preserves_error(family):
    observed = observe("athlete", {f"X-{family}-Usage": "100,300"})
    assert observed["error"] == "KeyError"
    assert observed["sleeps"] == []


@pytest.mark.parametrize("status", (429, 500))
def test_error_response_throttles_before_raising_without_retry(status):
    observed = observe(
        "athlete", BASE | {"X-RateLimit-Usage": "200,1000"}, status=status
    )
    assert observed["error"] == "Fault"
    assert observed["sleeps"] == [SHORT], observed
    assert len(observed["requests"]) == 1
    assert observed["events"] == ["http", ["sleep", SHORT], ["error", "Fault"]]


def test_two_argument_custom_callback_preserved():
    calls = []

    def custom(headers, method):
        calls.append((dict(headers), method))

    observed = observe("athlete", BASE, custom=custom)
    assert observed["sleeps"] == []
    assert calls[0][1] == "GET"
    assert all(calls[0][0][k] == v for k, v in BASE.items())


def test_reset_helpers_are_unchanged():
    assert limiter.get_seconds_until_next_quarter(NOW) == SHORT
    assert limiter.get_seconds_until_next_day(NOW) == LONG


@pytest.mark.parametrize(
    "base_class",
    (
        limiter.DefaultRateLimiter,
        limiter.RateLimiter,
        limiter.SleepingRateLimitRule,
    ),
)
def test_custom_call_overrides_are_not_bypassed(base_class):
    calls = []

    class CustomLimiter(base_class):
        def __call__(self, headers, method):
            calls.append((dict(headers), method))

    observed = observe("subscription", BASE, custom=CustomLimiter())
    assert observed["sleeps"] == []
    assert calls[0][1] == "POST"
    assert all(calls[0][0][k] == v for k, v in BASE.items())


@pytest.mark.parametrize(
    "base_class", (limiter.DefaultRateLimiter, limiter.SleepingRateLimitRule)
)
def test_overrides_delegating_to_super_keep_legacy_call_contract(base_class):
    calls = []

    class CustomLimiter(base_class):
        def __call__(self, headers, method):
            calls.append(method)
            super().__call__(headers, method)

    headers = BASE | {"X-ReadRateLimit-Usage": "100,300"}
    observed = observe("subscription", headers, custom=CustomLimiter())
    # The override still owns dispatch; delegating with two args has no URL.
    assert observed["sleeps"] == [0]
    assert calls == ["POST"]


def test_dynamic_mock_does_not_opt_into_internal_hook():
    custom = Mock()
    observed = observe("subscription", BASE, custom=custom)
    assert observed["sleeps"] == []
    custom.assert_called_once()
    custom._on_response.assert_not_called()
    assert custom.call_args.args[1] == "POST"


@pytest.mark.parametrize(
    "base_class",
    (
        limiter.RateLimiter,
        limiter.DefaultRateLimiter,
        limiter.SleepingRateLimitRule,
    ),
)
def test_spec_mock_retains_two_argument_callback(base_class):
    custom = Mock(spec=base_class)
    observed = observe("subscription", BASE, custom=custom)
    assert observed["sleeps"] == []
    custom.assert_called_once()
    assert custom.call_args.args[1] == "POST"
    assert all(custom.call_args.args[0][k] == v for k, v in BASE.items())


def test_nested_rate_limiters_receive_request_scope():
    inner = limiter.RateLimiter()
    inner.rules.append(limiter.SleepingRateLimitRule())
    outer = limiter.RateLimiter()
    outer.rules.append(inner)
    headers = BASE | {"X-ReadRateLimit-Usage": "100,300"}
    observed = observe("subscription", headers, custom=outer)
    assert observed["sleeps"] == [SHORT]
    assert observed["error"] is None


def test_unrelated_callback_response_method_is_not_called():
    calls = []

    class CustomLimiter:
        def __call__(self, headers, method):
            calls.append((dict(headers), method))

        def _on_response(self, response):
            raise AssertionError("This method is not a rate-limiter hook")

    observed = observe("athlete", BASE, custom=CustomLimiter())
    assert observed["sleeps"] == []
    assert len(calls) == 1
    assert calls[0][1] == "GET"
    assert all(calls[0][0][k] == v for k, v in BASE.items())


def test_unrelated_rule_response_method_is_not_called():
    calls = []

    class CustomRule:
        def __call__(self, headers, method):
            calls.append((dict(headers), method))

        def _on_response(self, response):
            raise AssertionError("This method is not a rate-limiter hook")

    custom = limiter.DefaultRateLimiter()
    custom.rules.append(CustomRule())
    observed = observe("subscription", BASE, custom=custom)
    assert observed["sleeps"] == [0]
    assert len(calls) == 1
    assert calls[0][1] == "POST"
    assert all(calls[0][0][k] == v for k, v in BASE.items())


@pytest.mark.parametrize("operation", ("create", "upload", "subscription"))
def test_upload_exemptions_follow_configured_api_base(operation):
    headers = BASE | {
        "X-ReadRateLimit-Usage": "100,5000",
        "X-RateLimit-Usage": "100,6000",
    }
    observed = observe(operation, headers, api_base="/proxy/api/v3")
    expected = LONG if operation == "subscription" else 0
    assert observed["sleeps"] == [expected]
    assert observed["error"] is None
    assert len(observed["requests"]) == 1


@pytest.mark.parametrize("endpoint", ("activities", "uploads"))
def test_upload_exemptions_preserve_lowercase_protocol_methods(endpoint):
    with patch.dict(os.environ, {}, clear=True):
        client = Client()
    with (
        responses.RequestsMock() as http,
        patch("stravalib.util.limiter.arrow.utcnow", return_value=NOW),
        patch("stravalib.util.limiter.time.sleep") as sleep,
    ):
        http.post(
            "https://www.strava.com/api/v3/" + endpoint,
            json={"id": 1},
            headers=BASE | {"X-ReadRateLimit-Usage": "100,300"},
        )
        client.protocol._request(endpoint, method="post")
        sleep.assert_called_once_with(0)
        assert len(http.calls) == 1


def test_custom_rules_receive_original_headers_and_method():
    custom = limiter.DefaultRateLimiter()
    recorded = Mock()
    custom.rules.append(recorded)
    observed = observe("upload", BASE, custom=custom)
    assert observed["sleeps"] == [0]
    recorded.assert_called_once()
    assert recorded.call_args.args[1] == "POST"
    assert all(recorded.call_args.args[0][k] == v for k, v in BASE.items())


def test_custom_sleeping_rule_override_is_preserved():
    calls = []

    class CustomRule(limiter.SleepingRateLimitRule):
        def __call__(self, headers, method):
            calls.append(method)

    custom = limiter.RateLimiter()
    custom.rules.append(CustomRule())
    assert observe("athlete", BASE, custom=custom)["sleeps"] == []
    assert calls == ["GET"]


def test_direct_sleeping_rule_receives_context_from_protocol():
    headers = BASE | {"X-ReadRateLimit-Usage": "100,300"}
    observed = observe(
        "subscription", headers, custom=limiter.SleepingRateLimitRule()
    )
    assert observed["sleeps"] == [SHORT]


def test_inherited_default_limiter_receives_context():
    class CustomLimiter(limiter.DefaultRateLimiter):
        pass

    headers = BASE | {"X-ReadRateLimit-Usage": "100,300"}
    assert observe("subscription", headers, custom=CustomLimiter())[
        "sleeps"
    ] == [SHORT]


@pytest.mark.parametrize(
    "family,operation,expected",
    (
        ("RateLimit", "subscription", SHORT),
        ("ReadRateLimit", "subscription", SHORT),
        ("ReadRateLimit", "upload", None),
    ),
)
def test_single_family_post_scope(family, operation, expected):
    headers = {f"X-{family}-Usage": "100,300", f"X-{family}-Limit": "100,5000"}
    assert observe(operation, headers)["sleeps"] == (
        [] if expected is None else [expected]
    )


def test_no_content_response_still_throttles():
    headers = BASE | {"X-ReadRateLimit-Usage": "100,300"}
    observed = observe("delete", headers, status=204)
    assert observed["error"] is None
    assert observed["sleeps"] == [SHORT]


def test_disabled_limiter_and_oauth_are_unchanged():
    with patch.dict(os.environ, {}, clear=True):
        client = Client(rate_limit_requests=False)
        oauth_client = Client()
    with (
        responses.RequestsMock() as http,
        patch("stravalib.util.limiter.time.sleep") as sleep,
    ):
        http.get(
            "https://www.strava.com/api/v3/athlete",
            json={"id": 1},
            headers=BASE,
        )
        client.get_athlete()
        http.post(
            "https://www.strava.com/oauth/token",
            json={
                "access_token": "fake",
                "refresh_token": "fake",
                "expires_at": 1,
            },
            headers=BASE,
        )
        oauth_client.exchange_code_for_token(123, "fake", "fake")
        sleep.assert_not_called()
        assert len(http.calls) == 2
