"""Utilities
==============
Rate limiter classes.

These are basically callables that when called register that a request was
issued. Depending on how they are configured that may cause a pause or
exception if a rate limit has been exceeded. It is up to the calling
code to ensure that these callables are invoked with every (successful?) call
to the backend API.

TODO: There is probably a better way to hook these into the requests library
directly

From the Strava docs:
  Strava API usage is limited on a per-application basis using a short term,
  15 minute, limit and a long term, daily, limit. The default rate limit allows
  600 requests every 15 minutes, with up to 30,000 requests per day.

  This limit allows applications to make 40 requests per minute for about
  half the day.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from logging import Logger
from typing import TYPE_CHECKING, Literal, NamedTuple

import arrow

if TYPE_CHECKING:
    from stravalib.protocol import RequestMethod


class RequestRate(NamedTuple):
    """Tuple containing request usage and usage limit."""

    short_usage: int
    """15-minute usage"""

    long_usage: int
    """Daily usage"""

    short_limit: int
    """15-minutes limit"""

    long_limit: int
    """Daily limit"""


def get_rates_from_response_headers(
    headers: dict[str, str], method: RequestMethod
) -> RequestRate | None:
    """Returns a namedtuple with values for short - and long usage and limit
    rates found in provided HTTP response headers

    Parameters
    ----------
    headers : dict
        HTTP response headers
    method : RequestMethod
        HTTP request method corresponding to the provided response headers

    Returns
    -------
    Optional[RequestRate]
        namedtuple with request rates or None if no rate-limit headers
        present in response.
    """
    usage_rates = limit_rates = []
    headers = {key.casefold(): value for key, value in headers.items()}

    if "x-readratelimit-usage" in headers and method == "GET":
        usage_rates = [
            int(v) for v in headers["x-readratelimit-usage"].split(",")
        ]
        limit_rates = [
            int(v) for v in headers["x-readratelimit-limit"].split(",")
        ]
    elif "x-ratelimit-usage" in headers:
        usage_rates = [int(v) for v in headers["x-ratelimit-usage"].split(",")]
        limit_rates = [int(v) for v in headers["x-ratelimit-limit"].split(",")]

    if usage_rates and limit_rates:
        return RequestRate(
            short_usage=usage_rates[0],
            long_usage=usage_rates[1],
            short_limit=limit_rates[0],
            long_limit=limit_rates[1],
        )
    else:
        return None


def _get_applicable_rates(
    headers: dict[str, str], non_upload: bool
) -> list[RequestRate]:
    """Keep applicable quota families separate, including their limits."""
    headers = {key.casefold(): value for key, value in headers.items()}
    methods: list[RequestMethod] = ["POST"]
    if non_upload and "x-readratelimit-usage" in headers:
        methods.append("GET")
    rates = []
    for method in methods:
        rate = get_rates_from_response_headers(headers, method)
        if rate is not None:
            rates.append(rate)
    return rates


def get_seconds_until_next_quarter(
    now: arrow.arrow.Arrow | None = None,
) -> int:
    """Returns the number of seconds until the next quarter of an hour. This is
    the short-term rate limit used by Strava.

    Parameters
    ----------
    now : arrow.arrow.Arrow
        A (utc) timestamp

    Returns
    -------
    int
        The number of seconds until the next quarter, as int
    """
    if now is None:
        now = arrow.utcnow()
    return (
        899
        - (
            now
            - now.replace(
                minute=(now.minute // 15) * 15, second=0, microsecond=0
            )
        ).seconds
    )


def get_seconds_until_next_day(now: arrow.arrow.Arrow | None = None) -> int:
    """Returns the number of seconds until the next day (utc midnight). This is
    the long-term rate limit used by Strava.

    Parameters
    ----------
    now : arrow.arrow.Arrow
        A (utc) timestamp

    Returns
    -------
    Int
        The number of seconds until next day, as int
    """
    if now is None:
        now = arrow.utcnow()
    return (now.ceil("day") - now).seconds


class SleepingRateLimitRule:
    """A rate limit rule that can be prioritized and can dynamically adapt its
    limits based on API responses. Given its priority, it will enforce a
    variable "cool-down" period after each response. When rate limits are
    reached within their period, this limiter will wait until the end of that
    period. It will NOT raise any kind of exception in this case.
    """

    def __init__(
        self,
        priority: Literal["low", "medium", "high"] = "high",
    ) -> None:
        """
        Constructs a new SleepingRateLimitRule.

        Parameters
        ----------
        priority : Literal["low", "medium", "high"]
            The priority for this rule. When 'low', the cool-down period
            after each request will be such that the long-term limits will
            not be exceeded. When 'medium', the cool-down period will be such
            that the short-term limits will not be exceeded.  When 'high',
            there will be no cool-down period.
        """
        if priority not in ["low", "medium", "high"]:
            raise ValueError(
                f'Invalid priority "{priority}", expecting one of "low", "medium" or "high"'
            )

        self.log = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )
        self.priority = priority

    def _get_wait_time(
        self,
        rates: RequestRate,
        seconds_until_short_limit: int,
        seconds_until_long_limit: int,
    ) -> float:
        """Calculate how much time user has until they can make another
        request"""

        # If limits are exceeded, wait until they reset
        if rates.long_usage >= rates.long_limit:
            self.log.warning("Long term API rate limit exceeded")
            return seconds_until_long_limit
        elif rates.short_usage >= rates.short_limit:
            self.log.warning("Short term API rate limit exceeded")
            return seconds_until_short_limit

        # High priority: no wait time
        if self.priority == "high":
            return 0

        # Calculate wait times for BOTH limits
        short_wait = seconds_until_short_limit / (
            rates.short_limit - rates.short_usage
        )
        long_wait = seconds_until_long_limit / (
            rates.long_limit - rates.long_usage
        )

        if self.priority == "medium":
            # Focus on short-term limit, but also respect daily limit
            # when at least half of the daily quota is used
            if rates.long_usage >= rates.long_limit / 2:
                return max(short_wait, long_wait)
            else:
                return short_wait
        elif self.priority == "low":
            # Spread requests over the day, but always respect both limits
            return max(short_wait, long_wait)

    def __call__(
        self, response_headers: dict[str, str], method: RequestMethod
    ) -> None:
        """Throttle without endpoint context, retaining method-based scope.

        GET responses account for both quotas. Other methods retain their
        overall-only scope because the upload exemptions need a URL.
        """
        self._sleep_for_rates(
            _get_applicable_rates(response_headers, non_upload=method == "GET")
        )

    def _on_response(
        self,
        response_headers: dict[str, str],
        method: RequestMethod,
        non_upload: bool,
    ) -> None:
        """Use endpoint context without bypassing custom __call__ overrides."""
        if type(self).__call__ is not SleepingRateLimitRule.__call__:
            self(response_headers, method)
            return
        self._sleep_for_rates(
            _get_applicable_rates(response_headers, non_upload)
        )

    def _sleep_for_rates(self, rates: list[RequestRate]) -> None:
        self.log.debug(f"Throttling based on rates: {rates}")

        if rates:
            short_reset = get_seconds_until_next_quarter()
            long_reset = get_seconds_until_next_day()
            time.sleep(
                max(
                    self._get_wait_time(rate, short_reset, long_reset)
                    for rate in rates
                )
            )
        else:
            self.log.warning("No rates present in response headers")


class RateLimiter:
    def __init__(self) -> None:
        self.log: Logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )
        self.rules: list[Callable[[dict[str, str], RequestMethod], None]] = []

    def __call__(self, args: dict[str, str], method: RequestMethod) -> None:
        """Register another request is being issued."""
        for r in self.rules:
            r(args, method)

    def _on_response(
        self, args: dict[str, str], method: RequestMethod, non_upload: bool
    ) -> None:
        """Pass request context to built-in rules, preserving custom calls."""
        if type(self).__call__ is not RateLimiter.__call__:
            self(args, method)
            return
        for rule in self.rules:
            _apply_rate_limiter(rule, args, method, non_upload=non_upload)


def _apply_rate_limiter(
    callback: Callable[[dict[str, str], RequestMethod], None],
    headers: dict[str, str],
    method: RequestMethod,
    *,
    non_upload: bool,
) -> None:
    """Give built-in limiters request scope without changing custom callbacks."""
    # Use the built-in methods so an unrelated private method on a custom
    # callback cannot opt into this path. Each method preserves __call__ overrides.
    if isinstance(callback, RateLimiter):
        RateLimiter._on_response(callback, headers, method, non_upload)
    elif isinstance(callback, SleepingRateLimitRule):
        SleepingRateLimitRule._on_response(
            callback, headers, method, non_upload
        )
    else:
        callback(headers, method)


class DefaultRateLimiter(RateLimiter):
    """Implements something similar to the default rate limit for Strava apps.

    See https://developers.strava.com/docs/rate-limits/ and
    https://communityhub.strava.com/t5/developer-knowledge-base/our-developer-program/ta-p/8849.

    Rate limits are enforced by throttling requests based on their method and
    client/app-specific limits imposed by Strava.

    The rate limiter supports three priority levels:

    - **high**: No cool-down period between requests. Requests are made as fast
      as possible until limits are reached, then waits until the limit period expires.
    - **medium**: Applies a cool-down period to avoid exceeding short-term limits
      (e.g., 600 requests per 15 minutes, actual limits are app-specific).
    - **low**: Applies a cool-down period to avoid exceeding long-term limits
      (e.g., 30,000 requests per day, actual limits are app-specific), spreading
      requests evenly throughout the day.

    Examples
    --------
    Using default (high priority) rate limiter::

        from stravalib.client import Client
        client = Client(access_token=token)  # Uses high priority by default

    Using a custom rate limiter with medium priority::

        from stravalib.client import Client
        from stravalib.util.limiter import DefaultRateLimiter

        rate_limiter = DefaultRateLimiter(priority="medium")
        client = Client(access_token=token, rate_limiter=rate_limiter)
    """

    def __init__(
        self, priority: Literal["low", "medium", "high"] = "high"
    ) -> None:
        """
        Initializes the rate limiter based on the given priority.

        Parameters
        ----------
        priority : Literal["low", "medium", "high"]
            The priority given to the requests. Default is "high"
            (i.e. no throttling).
        """

        super().__init__()

        self.rules.append(SleepingRateLimitRule(priority=priority))
