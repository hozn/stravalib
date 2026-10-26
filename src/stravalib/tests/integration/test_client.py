import datetime
import json
import logging
import os
import warnings
from unittest import mock
from unittest.mock import patch
from urllib.parse import urlparse

import pytest
import requests
import responses
from responses import matchers

from stravalib.client import ActivityUploader, Client
from stravalib.exc import (
    AccessUnauthorized,
    ActivityPhotoUploadFailed,
    ApplicationInactive,
    Fault,
)
from stravalib.model import (
    DetailedAthlete,
    Segment,
    SummaryAthlete,
    SummarySegment,
)
from stravalib.strava_model import SummaryActivity, Zones
from stravalib.tests import RESOURCES_DIR
from stravalib.unit_helper import miles

warnings.simplefilter("always")


@pytest.fixture
def zone_response():
    file_path = os.path.join(RESOURCES_DIR, "example_zone_response.json")
    with open(file_path) as file:
        data = json.load(file)
    return data


@pytest.fixture
def default_call_kwargs():
    """A fixture containing default input / call parameters for a create
    activity call to the strava API"""

    default_call_kwargs = {
        "name": "test",
        "start_date_local": "2022-01-01T09:00:00",
        "elapsed_time": 3600,
    }
    return default_call_kwargs


@pytest.fixture
def default_request_params():
    """A fixture containing default request parameters for a create activity
    request to the strava API"""

    default_request_params = {
        "name": "test",
        "start_date_local": "2022-01-01T09:00:00",
        "elapsed_time": "3600",
    }
    return default_request_params


@pytest.fixture
def raw_exchange_response():
    """Expected response from the protocol exchange_code_for_token method."""
    return (
        {
            "access_token": "123456",
            "refresh_token": "789sdf987",
            "expires_at": 1732417459,
        },
        {
            "id": 10295934,
            "username": "foo_bar",
            "resource_state": 2,
            "firstname": "Foo",
            "lastname": "Bar",
            "bio": "A bio",
            "city": "City",
            "state": "State",
            "country": "Country",
            "sex": "F",
            "premium": True,
            "summit": True,
        },
    )


def test_get_athlete(mock_strava_api, client):
    mock_strava_api.get("/athlete", response_update={"id": 42})
    athlete = client.get_athlete()
    assert isinstance(athlete, DetailedAthlete)
    assert athlete.id == 42
    assert athlete.measurement_preference == "feet"


def test_access_token_sent_in_authorization_header(mock_strava_api):
    """The access token is sent as a bearer token in the request header, and
    never in the URL query string (see RFC 6750 and issue #733)."""

    client_with_token = Client(access_token="token123")
    mock_strava_api.get("/athlete", response_update={"id": 42})
    client_with_token.get_athlete()

    request = mock_strava_api.calls[0].request
    assert request.headers["Authorization"] == "Bearer token123"
    assert "access_token" not in request.url


def test_no_authorization_header_on_token_refresh(mock_strava_api):
    """The token endpoint authenticates with the client id and secret. It
    gets no Authorization header, because the token there is expired."""

    client_with_token = Client(access_token="expired_token")
    mock_strava_api.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={
            "access_token": "new_token",
            "refresh_token": "new_refresh_token",
            "expires_at": 1732417459,
        },
    )
    client_with_token.refresh_access_token(
        client_id=123, client_secret="secret", refresh_token="refresh_token"
    )

    request = mock_strava_api.calls[0].request
    assert "Authorization" not in request.headers


def test_code_exchange_sends_credentials_in_form_body(mock_strava_api):
    """The authorization code grant sends the client secret and the code in
    a form-encoded body. The URL query string stays empty, because URLs are
    logged (RFC 6749 2.3.1, issue #740)."""

    client_without_token = Client()
    mock_strava_api.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={
            "access_token": "new_token",
            "refresh_token": "new_refresh_token",
            "expires_at": 1732417459,
        },
        match=[
            matchers.urlencoded_params_matcher(
                {
                    "client_id": "123",
                    "client_secret": "secret",
                    "code": "auth_code",
                    "grant_type": "authorization_code",
                }
            )
        ],
    )
    client_without_token.exchange_code_for_token(
        client_id=123, client_secret="secret", code="auth_code"
    )

    request = mock_strava_api.calls[0].request
    assert urlparse(request.url).query == ""


def test_token_refresh_sends_credentials_in_form_body(mock_strava_api):
    """The refresh grant sends the client secret and the refresh token in a
    form-encoded body. The URL query string stays empty (issue #740)."""

    client_with_token = Client(access_token="expired_token")
    mock_strava_api.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={
            "access_token": "new_token",
            "refresh_token": "new_refresh_token",
            "expires_at": 1732417459,
        },
        match=[
            matchers.urlencoded_params_matcher(
                {
                    "client_id": "123",
                    "client_secret": "secret",
                    "refresh_token": "refresh_token",
                    "grant_type": "refresh_token",
                }
            )
        ],
    )
    client_with_token.refresh_access_token(
        client_id=123, client_secret="secret", refresh_token="refresh_token"
    )

    request = mock_strava_api.calls[0].request
    assert urlparse(request.url).query == ""


def test_no_authorization_header_without_access_token(mock_strava_api, client):
    """A client without an access token sends no Authorization header."""

    mock_strava_api.get("/athlete", response_update={"id": 42})
    client.get_athlete()

    assert "Authorization" not in mock_strava_api.calls[0].request.headers


@pytest.mark.parametrize(
    "access_token,refresh_token,expected_token,token_type_hint",
    (
        (
            "expired+token&value=1",
            "refresh+token&value=2",
            "refresh+token&value=2",
            "refresh_token",
        ),
        (
            None,
            "refresh+token&value=2",
            "refresh+token&value=2",
            "refresh_token",
        ),
        (
            "",
            "refresh+token&value=2",
            "refresh+token&value=2",
            "refresh_token",
        ),
        ("access+token&value=1", None, "access+token&value=1", "access_token"),
        ("access+token&value=1", "", "access+token&value=1", "access_token"),
    ),
    ids=(
        "prefer-refresh-over-expired-access",
        "refresh-without-access",
        "refresh-with-empty-access",
        "access-without-refresh",
        "access-with-empty-refresh",
    ),
)
def test_deauthorize_revokes_without_refreshing(
    mock_strava_api,
    mock_strava_env,
    caplog,
    access_token,
    refresh_token,
    expected_token,
    token_type_hint,
):
    """Prefer the refresh token, falling back to access, without refreshing."""
    rate_limiter = mock.Mock()
    client_with_token = Client(
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires=1,
        rate_limiter=rate_limiter,
    )
    mock_strava_api.add(
        responses.POST,
        "https://www.strava.com/oauth/revoke",
        body="",
        status=200,
        match=[
            matchers.urlencoded_params_matcher(
                {"token": expected_token, "token_type_hint": token_type_hint}
            )
        ],
    )

    with (
        patch.object(
            client_with_token.protocol, "refresh_expired_token"
        ) as refresh,
        caplog.at_level(logging.DEBUG, logger="stravalib"),
    ):
        assert client_with_token.deauthorize() is None

    request = mock_strava_api.calls[0].request
    assert request.url == "https://www.strava.com/oauth/revoke"
    assert urlparse(request.url).query == ""
    assert request.headers["Authorization"] == "Basic MTIzNDU6MTIzZ2hwMjM0"
    assert (
        request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    )
    assert len(mock_strava_api.calls) == 1
    refresh.assert_not_called()
    rate_limiter.assert_not_called()
    assert client_with_token.access_token == access_token
    assert client_with_token.refresh_token == refresh_token
    assert client_with_token.token_expires == 1
    for value in (
        access_token,
        refresh_token,
        "12345",
        "123ghp234",
        "MTIzNDU6MTIzZ2hwMjM0",
    ):
        if value:
            assert value not in caplog.text


def test_deauthorize_keeps_authentication_scoped_to_request(
    mock_strava_api, mock_strava_env
):
    """Basic credentials never become defaults on the shared session."""
    session = requests.Session()
    session.headers["X-Test"] = "preserved"
    original_headers = session.headers.copy()
    client_with_token = Client(
        access_token="token123",
        requests_session=session,
        rate_limit_requests=False,
    )
    mock_strava_api.add(
        responses.POST, "https://www.strava.com/oauth/revoke", body=""
    )
    mock_strava_api.add(
        responses.GET,
        "https://www.strava.com/api/v3/athlete",
        json={"id": 42},
    )
    mock_strava_api.add(
        responses.PUT, "https://uploads.example.com/photo", body=""
    )

    client_with_token.deauthorize()
    assert session.auth is None
    assert session.headers == original_headers

    client_with_token.get_athlete()
    session.put("https://uploads.example.com/photo", data=b"photo")

    api_request = mock_strava_api.calls[1].request
    upload_request = mock_strava_api.calls[2].request
    assert api_request.headers["Authorization"] == "Bearer token123"
    assert "Authorization" not in upload_request.headers


@pytest.mark.parametrize(
    "field,value",
    (
        ("client_id", None),
        ("client_id", 0),
        ("client_secret", None),
        ("client_secret", ""),
    ),
)
def test_deauthorize_requires_credentials(
    mock_strava_api, mock_strava_env, field, value
):
    """Missing authentication inputs fail locally before any HTTP call."""
    client_with_token = Client(refresh_token="refresh123")
    setattr(client_with_token.protocol, field, value)

    with pytest.raises(
        ValueError, match="STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET"
    ):
        client_with_token.deauthorize()

    assert not mock_strava_api.calls


@pytest.mark.parametrize("access_token", (None, ""))
@pytest.mark.parametrize("refresh_token", (None, ""))
def test_deauthorize_requires_access_or_refresh_token(
    mock_strava_api, mock_strava_env, access_token, refresh_token
):
    client_without_token = Client(
        access_token=access_token, refresh_token=refresh_token
    )

    with pytest.raises(
        ValueError, match="Deauthorization requires an access or refresh token"
    ):
        client_without_token.deauthorize()

    assert not mock_strava_api.calls


@pytest.mark.parametrize(
    "status,expected_exception",
    ((400, Fault), (401, AccessUnauthorized), (503, Fault)),
)
def test_deauthorize_preserves_protocol_errors(
    mock_strava_api, mock_strava_env, status, expected_exception
):
    client_with_token = Client(access_token="token123")
    mock_strava_api.add(
        responses.POST,
        "https://www.strava.com/oauth/revoke",
        status=status,
        body="",
    )

    with pytest.raises(expected_exception) as error:
        client_with_token.deauthorize()

    assert error.value.response is mock_strava_api.calls[0].response
    assert len(mock_strava_api.calls) == 1


def test_deauthorize_rejects_redirects(mock_strava_api, mock_strava_env):
    """A redirect must not replay the revocation token to another host."""
    client_with_token = Client(access_token="token123")
    mock_strava_api.add(
        responses.POST,
        "https://www.strava.com/oauth/revoke",
        status=307,
        headers={"Location": "https://other.example.com/revoke"},
    )

    with pytest.raises(Fault) as error:
        client_with_token.deauthorize()

    assert error.value.response.status_code == 307
    assert len(mock_strava_api.calls) == 1


def test_get_athlete_zones(mock_strava_api, client):
    json_response = {
        "heart_rate": {
            "custom_zones": False,
            "zones": [
                {"min": 0, "max": 123},
                {"min": 123, "max": 153},
                {"min": 153, "max": 169},
                {"min": 169, "max": 184},
                {"min": 184, "max": -1},
            ],
        }
    }
    # We overwrite the response from the mock as the example in the swagger
    # specification is incorrect
    mock_strava_api.get("/athlete/zones", json=json_response)
    zones = client.get_athlete_zones()
    assert isinstance(zones, Zones)


@pytest.mark.parametrize(
    "include_all_efforts,expected_url",
    (
        (None, "/activities/42?include_all_efforts=False"),
        (False, "/activities/42?include_all_efforts=False"),
        (True, "/activities/42?include_all_efforts=True"),
    ),
)
def test_get_activity(
    mock_strava_api, client, include_all_efforts, expected_url
):
    test_activity_id = 42
    mock_strava_api.get(
        "/activities/{id}", response_update={"id": test_activity_id}
    )
    if include_all_efforts is not None:
        activity = client.get_activity(test_activity_id, include_all_efforts)
    else:
        activity = client.get_activity(test_activity_id)
    assert mock_strava_api.calls[-1].request.url.endswith(expected_url)
    assert activity.id == test_activity_id


def test_activity_with_segment_that_that_is_not_ride_or_run(
    mock_strava_api, client
):
    """
    Make sure that activity that are not run are ride can still have segment.

    See issue https://github.com/stravalib/stravalib/issues/432
    """
    test_activity_id = 1907
    mock_strava_api.get(
        "/activities/{id}",
        response_update={
            "id": test_activity_id,
            "type": "Hike",
            "segment_efforts": [
                {
                    "id": 3125507031446243384,
                    "resource_state": 2,
                    "name": "Landmannalaugavegur Climb",
                    "activity": {
                        "id": 9634609164,
                        "visibility": "followers_only",
                        "resource_state": 1,
                    },
                    "athlete": {"id": 69911568, "resource_state": 1},
                    "elapsed_time": 454,
                    "moving_time": 426,
                    "start_date": "2023-08-12T05:22:38Z",
                    "start_date_local": "2023-08-12T05:22:38Z",
                    "distance": 709.74,
                    "start_index": 91,
                    "end_index": 213,
                    "average_cadence": 47.7,
                    "device_watts": False,
                    "segment": {
                        "id": 837087,
                        "resource_state": 2,
                        "name": "Landmannalaugavegur Climb",
                        "activity_type": "Hike",
                        "distance": 709.74,
                        "average_grade": 7.7,
                        "maximum_grade": 427.6,
                        "elevation_high": 624.4,
                        "elevation_low": 570.0,
                        "start_latlng": [
                            63.99094129912555,
                            -19.063721196725965,
                        ],
                        "end_latlng": [63.99059135466814, -19.075878812000155],
                        "elevation_profile": None,
                        "climb_category": 0,
                        "city": None,
                        "state": "Suðurland",
                        "country": "Iceland",
                        "private": False,
                        "hazardous": False,
                        "starred": False,
                    },
                    "pr_rank": None,
                    "achievements": [],
                    "visibility": "followers_only",
                    "hidden": False,
                }
            ],
        },
    )
    activity = client.get_activity(test_activity_id)


def test_get_activity_laps(mock_strava_api, client):
    mock_strava_api.get(
        "/activities/{id}/laps",
        response_update={"distance": 1000},
        n_results=2,
    )
    laps = list(client.get_activity_laps(42))
    assert len(laps) == 2
    assert laps[0].distance == 1000


def test_get_activity_zones(mock_strava_api, client, zone_response):
    """Returns an activities associated zone (related to heart rate and power)

    Notes
    -----
    There is no example response for this endpoint in swagger.json so
    we created a sample json file with the return that we are currently
    seeing. Thus this method could break at any time if Strava changes
    the response output.

    """

    mock_strava_api.get("/activities/{id}/zones", json=zone_response)

    # https://developers.strava.com/docs/reference/#api-models-integer
    activity_zones = client.get_activity_zones(42)
    assert len(activity_zones) == 2
    assert activity_zones[0].type == "heartrate"
    assert activity_zones[0].sensor_based


def test_get_activity_streams(mock_strava_api, client):
    query_params = {"keys": "distance", "key_by_type": True}
    mock_strava_api.get(
        "/activities/{id}/streams",
        json={
            "distance": {
                "data": [1.0, 2.0, 3.0],
                "series_type": "distance",
                "original_size": 9,
                "resolution": "high",
            }
        },
        match=[matchers.query_param_matcher(query_params)],
    )
    streams = client.get_activity_streams(42, types=["distance"])
    assert streams["distance"].data == [1.0, 2.0, 3.0]


def test_get_effort_streams(mock_strava_api, client):
    query_params = {"keys": "distance", "key_by_type": True}
    mock_strava_api.get(
        "/segment_efforts/{id}/streams",
        json={
            "distance": {
                "data": [1.0, 2.0, 3.0],
                "series_type": "distance",
                "original_size": 9,
                "resolution": "high",
            }
        },
        match=[matchers.query_param_matcher(query_params)],
    )
    streams = client.get_effort_streams(42, types=["distance"])
    assert streams["distance"].data == [1.0, 2.0, 3.0]


def test_get_segment_streams(mock_strava_api, client):
    query_params = {"keys": "distance", "key_by_type": True}
    mock_strava_api.get(
        "/segments/{id}/streams",
        json={
            "distance": {
                "data": [1.0, 2.0, 3.0],
                "series_type": "distance",
                "original_size": 9,
                "resolution": "high",
            }
        },
        match=[matchers.query_param_matcher(query_params)],
    )
    streams = client.get_segment_streams(42, types=["distance"])
    assert streams["distance"].data == [1.0, 2.0, 3.0]


def test_get_activity_streams_no_type_specified(mock_strava_api, client):
    query_params = {
        "keys": "time,distance,latlng,altitude,velocity_smooth,heartrate,cadence,watts,temp,moving,grade_smooth",
        "key_by_type": True,
    }
    mock_strava_api.get(
        "/activities/{id}/streams",
        json={
            "distance": {
                "data": [1.0, 2.0, 3.0],
                "original_size": 9,
                "resolution": "high",
            }
        },
        match=[matchers.query_param_matcher(query_params)],
    )
    streams = client.get_activity_streams(42)
    assert streams["distance"].data == [1.0, 2.0, 3.0]


def test_get_activity_streams_invalid_type(mock_strava_api, client):
    with pytest.raises(ValueError):
        streams = client.get_activity_streams(
            42, types=["distance", "hhjj", "npt"]
        )


def test_get_activity_streams_resolution_unofficial(mock_strava_api, client):
    mock_strava_api.get(
        "/activities/{id}/streams",
        json={
            "distance": {
                "data": [1.0, 2.0, 3.0],
                "series_type": "distance",
                "original_size": 9,
                "resolution": "high",
            }
        },
    )
    with pytest.warns(FutureWarning):
        streams = client.get_activity_streams(
            42, types=["distance"], resolution="high"
        )


def test_get_activity_streams_series_type_unofficial(mock_strava_api, client):
    mock_strava_api.get(
        "/activities/{id}/streams",
        json={
            "distance": {
                "data": [1.0, 2.0, 3.0],
                "series_type": "distance",
                "original_size": 9,
                "resolution": "high",
            }
        },
    )
    with pytest.warns(FutureWarning):
        streams = client.get_activity_streams(
            42, types=["distance"], series_type="distance"
        )


@pytest.mark.parametrize(
    "update_kwargs,expected_body,expected_warning,expected_exception",
    (
        ({}, {}, None, None),
        ({"activity_type": "Run"}, {"type": "run"}, DeprecationWarning, None),
        ({"sport_type": "TrailRun"}, {"sport_type": "TrailRun"}, None, None),
        (
            {"activity_type": "Run", "sport_type": "TrailRun"},
            {"sport_type": "TrailRun"},
            None,
            None,
        ),
        # private is no longer supported by the API: warn but do not send it
        ({"private": True}, {}, DeprecationWarning, None),
        ({"commute": True}, {"commute": True}, None, None),
        ({"trainer": True}, {"trainer": True}, None, None),
        ({"gear_id": "fb42"}, {"gear_id": "fb42"}, None, None),
        ({"description": "foo"}, {"description": "foo"}, None, None),
        # device_name is no longer supported: warn but do not send it
        (
            {"device_name": "foo"},
            {},
            DeprecationWarning,
            None,
        ),
        ({"hide_from_home": False}, {"hide_from_home": False}, None, None),
        (
            {"name": "My awesome activity"},
            {"name": "My awesome activity"},
            None,
            None,
        ),
    ),
)
def test_update_activity(
    mock_strava_api,
    client,
    update_kwargs,
    expected_body,
    expected_warning,
    expected_exception,
):
    activity_id = 42

    def _call_update_activity():
        _ = client.update_activity(activity_id, **update_kwargs)
        request = mock_strava_api.calls[-1].request
        assert json.loads(request.body) == expected_body

    if expected_exception:
        with pytest.raises(expected_exception):
            _call_update_activity()
    else:
        mock_strava_api.put("/activities/{id}", status=200)
        if expected_warning:
            with pytest.warns(expected_warning):
                _call_update_activity()
        else:
            _call_update_activity()


@pytest.mark.parametrize(
    "activity_file_type,data_type,upload_kwargs,expected_params,expected_warning,expected_exception",
    (
        ("file", "tcx", {}, {"data_type": "tcx"}, None, None),
        ("str", "tcx", {}, {"data_type": "tcx"}, None, None),
        ("bytes", "tcx", {}, {"data_type": "tcx"}, None, None),
        ("not_supported", "tcx", {}, {}, None, TypeError),
        ("file", "invalid", {}, {}, None, ValueError),
        (
            "file",
            "tcx",
            {"name": "name"},
            {"data_type": "tcx", "name": "name"},
            None,
            None,
        ),
        (
            "file",
            "tcx",
            {"description": "descr"},
            {"data_type": "tcx", "description": "descr"},
            None,
            None,
        ),
        (
            "file",
            "tcx",
            {"activity_type": "run"},
            {"data_type": "tcx", "activity_type": "run"},
            FutureWarning,
            None,
        ),
        (
            "file",
            "tcx",
            {"activity_type": "Run"},
            {"data_type": "tcx", "activity_type": "run"},
            FutureWarning,
            None,
        ),
        ("file", "tcx", {"activity_type": "sleep"}, None, None, ValueError),
        (
            "file",
            "tcx",
            {"private": True},
            {"data_type": "tcx", "private": "1"},
            DeprecationWarning,
            None,
        ),
        (
            "file",
            "tcx",
            {"external_id": 42},
            {"data_type": "tcx", "external_id": "42"},
            None,
            None,
        ),
        (
            "file",
            "tcx",
            {"trainer": True},
            {"data_type": "tcx", "trainer": "1"},
            None,
            None,
        ),
        (
            "file",
            "tcx",
            {"commute": False},
            {"data_type": "tcx", "commute": "0"},
            None,
            None,
        ),
    ),
)
def test_upload_activity(
    mock_strava_api,
    client,
    activity_file_type,
    data_type,
    upload_kwargs,
    expected_params,
    expected_warning,
    expected_exception,
):
    init_upload_response = {
        "id": 1,
        "id_str": "abc",
        "external_id": "abc",
        "status": "default_status",
        "error": "",
    }

    def _call_and_assert(file):
        _ = client.upload_activity(file, data_type, **upload_kwargs)
        assert mock_strava_api.calls[-1].request.params == expected_params

    def _call_upload(file):
        if expected_exception:
            with pytest.raises(expected_exception):
                _call_and_assert(file)
        else:
            mock_strava_api.post(
                "/uploads", status=201, json=init_upload_response
            )
            if expected_warning:
                with pytest.warns(expected_warning):
                    _call_and_assert(file)
            else:
                _call_and_assert(file)

    with open(os.path.join(RESOURCES_DIR, "sample.tcx")) as f:
        if activity_file_type == "file":
            _call_upload(f)
        elif activity_file_type == "str":
            _call_upload(f.read())
        elif activity_file_type == "bytes":
            _call_upload(f.read().encode("utf-8"))
        else:
            _call_upload({})


@pytest.mark.parametrize(
    "update_kwargs,expected_params,expected_warning,expected_exception",
    (
        ({}, {}, None, None),
        ({"city": "foo"}, {"city": "foo"}, DeprecationWarning, None),
        ({"state": "foo"}, {"state": "foo"}, DeprecationWarning, None),
        ({"country": "foo"}, {"country": "foo"}, DeprecationWarning, None),
        ({"sex": "foo"}, {"sex": "foo"}, DeprecationWarning, None),
        ({"weight": "foo"}, {}, None, ValueError),
        ({"weight": "99.9"}, {"weight": "99.9"}, None, None),
        ({"weight": 99.9}, {"weight": "99.9"}, None, None),
        ({"weight": 99}, {"weight": "99.0"}, None, None),
    ),
)
def test_update_athlete(
    mock_strava_api,
    client,
    update_kwargs,
    expected_params,
    expected_warning,
    expected_exception,
):
    def _call_and_assert():
        _ = client.update_athlete(**update_kwargs)
        assert mock_strava_api.calls[-1].request.params == expected_params

    if expected_exception:
        with pytest.raises(expected_exception):
            _call_and_assert()
    else:
        mock_strava_api.put("/athlete", status=200)
        if expected_warning:
            with pytest.warns(expected_warning):
                _call_and_assert()
        else:
            _call_and_assert()


@pytest.mark.parametrize(
    "extra_create_kwargs,extra_expected_params,expected_exception",
    (
        (
            {
                "sport_type": "TrailRun",
                "start_date_local": datetime.datetime(2022, 1, 1, 10, 0, 0),
            },
            {
                "sport_type": "TrailRun",
                "start_date_local": "2022-01-01T10:00:00Z",
            },
            None,
        ),
        (
            {
                "sport_type": "TrailRun",
                "elapsed_time": datetime.timedelta(minutes=1),
            },
            {"sport_type": "TrailRun", "elapsed_time": "60"},
            None,
        ),
        (
            {"sport_type": "TrailRun", "distance": 1000},
            {"sport_type": "TrailRun", "distance": "1000"},
            None,
        ),
        (
            {"sport_type": "TrailRun", "distance": miles(1)},
            {"sport_type": "TrailRun", "distance": "1609.344"},
            None,
        ),
        (
            {"sport_type": "TrailRun", "description": "foo"},
            {"sport_type": "TrailRun", "description": "foo"},
            None,
        ),
        (
            {"description": "foo"},
            {"description": "foo"},
            ValueError,
        ),
    ),
)
def test_create_activity(
    default_call_kwargs,
    default_request_params,
    mock_strava_api,
    client,
    extra_create_kwargs,
    extra_expected_params,
    expected_exception,
):
    """Test what happens when create activity receives valid and invalid
    sport type values and also what happens when a required API item
    is missing."""

    call_kwargs = default_call_kwargs | extra_create_kwargs
    expected_params = default_request_params | extra_expected_params

    def _call_and_assert():
        _ = client.create_activity(**call_kwargs)
        assert mock_strava_api.calls[-1].request.params == expected_params

    if expected_exception:
        with pytest.raises(expected_exception):
            _call_and_assert()
    else:
        mock_strava_api.post("/activities", status=201)
        _call_and_assert()


def test_activity_uploader(mock_strava_api, client):
    test_activity_id = 42
    init_upload_response = {
        "id": 1,
        "id_str": "abc",
        "external_id": "abc",
        "status": "default_status",
        "error": "",
    }
    mock_strava_api.post("/uploads", status=201, json=init_upload_response)
    mock_strava_api.get("/uploads/{uploadId}", json=init_upload_response)
    mock_strava_api.get("/uploads/{uploadId}", json=init_upload_response)
    mock_strava_api.get(
        "/uploads/{uploadId}",
        json={**init_upload_response, "activity_id": test_activity_id},
    )
    mock_strava_api.get(
        "/activities/{id}", response_update={"id": test_activity_id}
    )
    with open(os.path.join(RESOURCES_DIR, "sample.tcx")) as activity_file:
        uploader = client.upload_activity(activity_file, data_type="tcx")
        assert uploader.is_processing
        activity = uploader.wait()
        assert uploader.is_complete
        assert activity.id == test_activity_id


def test_activity_uploader_error_list(client):
    """Test ActivityUploader handles errors field as a list."""
    from stravalib.exc import ActivityUploadFailed

    response = {
        "id": 123,
        "external_id": "test_external_id",
        "errors": ["Error 1", "Error 2", "Error 3"],
    }
    uploader = ActivityUploader(client, response=response, raise_exc=False)
    assert uploader.error == "Error 1; Error 2; Error 3"
    assert uploader.is_error

    with pytest.raises(ActivityUploadFailed) as exc_info:
        uploader.raise_for_error()
    error_msg = str(exc_info.value)
    assert "Activity upload failed: Error 1; Error 2; Error 3" in error_msg
    assert "Upload ID: 123" in error_msg
    assert "External ID: test_external_id" in error_msg


def test_activity_uploader_error_dict(client):
    """Test ActivityUploader handles errors field as a dict."""
    from stravalib.exc import ActivityUploadFailed

    response = {
        "id": 456,
        "external_id": "test_ext_id",
        "errors": {"field1": "error message 1", "field2": "error message 2"},
    }
    uploader = ActivityUploader(client, response=response, raise_exc=False)
    assert "field1: error message 1" in uploader.error
    assert "field2: error message 2" in uploader.error
    assert uploader.is_error

    with pytest.raises(ActivityUploadFailed) as exc_info:
        uploader.raise_for_error()
    error_msg = str(exc_info.value)
    assert "Activity upload failed:" in error_msg
    assert "Upload ID: 456" in error_msg
    assert "External ID: test_ext_id" in error_msg


def test_activity_uploader_error_processing(client):
    """Test ActivityUploader raises ErrorProcessingActivity for processing errors."""
    from stravalib.exc import ErrorProcessingActivity

    response = {
        "id": 789,
        "external_id": "proc_error_id",
        "error": "Error processing your activity",
    }
    uploader = ActivityUploader(client, response=response, raise_exc=False)
    assert uploader.is_error

    with pytest.raises(ErrorProcessingActivity) as exc_info:
        uploader.raise_for_error()
    error_msg = str(exc_info.value)
    assert (
        "Activity upload failed: Error processing your activity" in error_msg
    )
    assert "Upload ID: 789" in error_msg
    assert "External ID: proc_error_id" in error_msg


def test_activity_uploader_error_without_ids(client):
    """Test ActivityUploader error message without upload_id and external_id."""
    from stravalib.exc import ActivityUploadFailed

    response = {
        "error": "Generic upload error",
    }
    uploader = ActivityUploader(client, response=response, raise_exc=False)
    assert uploader.is_error

    with pytest.raises(ActivityUploadFailed) as exc_info:
        uploader.raise_for_error()
    error_msg = str(exc_info.value)
    assert "Activity upload failed: Generic upload error" in error_msg
    # Should not contain ID information
    assert "Upload ID:" not in error_msg
    assert "External ID:" not in error_msg


def test_get_route(mock_strava_api, client):
    with open(
        os.path.join(RESOURCES_DIR, "example_route_response.json")
    ) as route_response_fp:
        route_response = json.load(route_response_fp)
    mock_strava_api.get("/routes/{id}", status=200, json=route_response)
    route = client.get_route(42)
    assert route.name == "15k, no traffic"


@responses.activate
def test_create_subscription(mock_strava_api, client):
    """The subscription credentials travel in a form-encoded body. The URL
    query string stays empty, because URLs are logged (issue #740)."""

    responses.post(
        "https://www.strava.com/api/v3/push_subscriptions",
        json={
            "application_id": 42,
            "object_type": "activity",
            "aspect_type": "create",
            "callback_url": "https://foobar.com",
            "created_at": 1674660406,
        },
        status=200,
        match=[
            matchers.urlencoded_params_matcher(
                {
                    "client_id": "42",
                    "client_secret": "42",
                    "callback_url": "https://foobar.com",
                    "verify_token": "STRAVA",
                }
            )
        ],
    )
    created_subscription = client.create_subscription(
        42, 42, "https://foobar.com"
    )
    assert created_subscription.application_id == 42

    request = responses.calls[0].request
    assert urlparse(request.url).query == ""


@responses.activate
def test_delete_subscription_sends_credentials_in_form_body(
    mock_strava_api, client
):
    """The credentials travel in a form-encoded body, so the client secret
    does not reach the URL. Strava documents the query-string form for this
    call and accepts a body undocumented, which is why this test exists: it
    is the guard that would go red if Strava stopped reading it (#740)."""

    responses.add(
        responses.DELETE,
        "https://www.strava.com/api/v3/push_subscriptions/1",
        status=204,
        match=[
            matchers.urlencoded_params_matcher(
                {"client_id": "42", "client_secret": "secret"}
            )
        ],
    )
    client.delete_subscription(1, 42, "secret")

    request = responses.calls[0].request
    assert urlparse(request.url).query == ""


@pytest.mark.parametrize(
    "raw,expected_verify_token,expected_response,expected_exception",
    (
        (
            {"hub.verify_token": "a", "hub.challenge": "b"},
            "a",
            {"hub.challenge": "b"},
            None,
        ),
        (
            {"hub.verify_token": "foo", "hub.challenge": "b"},
            "a",
            None,
            AssertionError,
        ),
    ),
)
def test_handle_subscription_callback(
    client, raw, expected_verify_token, expected_response, expected_exception
):
    if expected_exception:
        with pytest.raises(expected_exception):
            client.handle_subscription_callback(raw, expected_verify_token)
    else:
        assert (
            client.handle_subscription_callback(raw, expected_verify_token)
            == expected_response
        )


@pytest.mark.parametrize(
    "limit,n_raw_results,expected_n_segments",
    (
        (None, 0, 0),
        (None, 10, 10),
        (10, 10, 10),
        (10, 20, 10),
        (10, 1, 1),
        (10, 0, 0),
    ),
)
def test_get_starred_segments(
    mock_strava_api, client, limit, n_raw_results, expected_n_segments
):
    mock_strava_api.get(
        "/segments/starred",
        response_update={"name": "test_segment"},
        n_results=n_raw_results,
    )
    kwargs = {"limit": limit} if limit is not None else {}
    segment_list = list(client.get_starred_segments(**kwargs))
    assert len(segment_list) == expected_n_segments
    if expected_n_segments > 0:
        assert isinstance(segment_list[0], SummarySegment)
        assert segment_list[0].name == "test_segment"


@pytest.mark.parametrize("starred", (True, False))
def test_star_segment(mock_strava_api, client, starred):
    mock_strava_api.put(
        "/segments/{id}/starred",
        response_update={"starred": starred},
    )
    segment = client.star_segment(42, starred)
    request = mock_strava_api.calls[-1].request
    assert request.url.endswith("/segments/42/starred")
    assert json.loads(request.body) == {"starred": starred}
    assert isinstance(segment, Segment)
    assert segment.starred is starred


def test_get_club(mock_strava_api, client):
    mock_strava_api.get("/clubs/{id}", response_update={"name": "foo"})
    club = client.get_club(42)
    assert club.name == "foo"


@pytest.mark.parametrize("n_clubs", (0, 2))
def test_get_athlete_clubs_iterator(mock_strava_api, client, n_clubs):
    """Test that athlete clubs returns the correct
    number of clubs"""

    # Create a mock instance with the club name update to my club
    mock_strava_api.get(
        "/athlete/clubs", response_update={"name": "myclub"}, n_results=n_clubs
    )
    # Convert iterator to list
    clubs = list(client.get_athlete_clubs())
    assert len(clubs) == n_clubs
    if clubs:
        assert clubs[0].name == "myclub"


@pytest.mark.parametrize(
    "athlete_id,authenticated_athlete,expected_biggest_ride_distance,expected_exception",
    (
        (42, True, 1000, None),
        (42, False, None, AccessUnauthorized),
        (None, True, 1000, None),
    ),
)
def test_get_athlete_stats(
    mock_strava_api,
    client,
    athlete_id,
    authenticated_athlete,
    expected_biggest_ride_distance,
    expected_exception,
):
    if athlete_id is None:
        mock_strava_api.get("/athlete", response_update={"id": 42})
    if authenticated_athlete:
        mock_strava_api.get(
            "/athletes/{id}/stats",
            response_update={
                "biggest_ride_distance": expected_biggest_ride_distance
            },
        )
    else:
        mock_strava_api.get(
            "/athletes/{id}/stats",
            json=[
                {
                    "resource": "Athlete",
                    "field": "access_token",
                    "code": "invalid",
                }
            ],
            status=401,
        )
    if expected_exception:
        with pytest.raises(expected_exception) as exc_info:
            client.get_athlete_stats(athlete_id)
        # Verify the enhanced error message
        error_msg = str(exc_info.value)
        assert (
            f"Unable to retrieve stats for athlete {athlete_id}" in error_msg
        )
        assert "currently authenticated athlete" in error_msg
    else:
        stats = client.get_athlete_stats(athlete_id)
        assert stats.biggest_ride_distance == expected_biggest_ride_distance


def test_get_gear(mock_strava_api, client):
    mock_strava_api.get("/gear/{id}", response_update={"name": "foo_bike"})
    assert client.get_gear(42).name == "foo_bike"


@pytest.mark.parametrize(
    "limit,n_raw_results,expected_n_activities",
    (
        (None, 10, 10),
        (None, 0, 0),
        (10, 10, 10),
        (10, 20, 10),
        (10, 1, 1),
        (10, 0, 0),
    ),
)
def test_get_activities(
    mock_strava_api, client, limit, n_raw_results, expected_n_activities
):
    mock_strava_api.get(
        "/athlete/activities",
        response_update={"name": "test_activity"},
        n_results=n_raw_results,
    )
    kwargs = {"limit": limit} if limit is not None else {}
    activity_list = list(client.get_activities(**kwargs))
    assert len(activity_list) == expected_n_activities
    if expected_n_activities > 0:
        assert isinstance(activity_list[0], SummaryActivity)
        assert activity_list[0].name == "test_activity"


def test_get_activities_quantity_addition(mock_strava_api, client):
    mock_strava_api.get(
        "/athlete/activities",
        response_update={"distance": 1000.0},
        n_results=2,
    )
    act_list = list(client.get_activities(limit=2))
    total_d = 0
    total_d += act_list[0].distance
    total_d += act_list[1].distance
    assert total_d == 2000.0


def test_get_segment(mock_strava_api, client):
    mock_strava_api.get("/segments/{id}", response_update={"name": "foo"})
    segment = client.get_segment(42)
    assert segment.name == "foo"


def test_get_segment_effort(mock_strava_api, client):
    mock_strava_api.get(
        "/segment_efforts/{id}", response_update={"max_heartrate": 170}
    )
    effort = client.get_segment_effort(42)
    assert effort.max_heartrate == 170


@pytest.mark.parametrize(
    "params, warning_type, warning_message",
    [
        (
            {"segment_id": 2345, "athlete_id": 12345},
            DeprecationWarning,
            'The "athlete_id" parameter is unsupported',
        ),
        (
            {"segment_id": 2345, "limit": 10},
            DeprecationWarning,
            'The "limit" parameter is deprecated',
        ),
    ],
)
def test_get_segment_efforts_warnings(
    params, warning_type, warning_message, mock_strava_api, client
):
    """Test that if provided with deprecated params, the user receives a
    warning."""

    mock_strava_api.get(
        "/segment_efforts",
        response_update={"name": "Best Run Ever"},
        n_results=1,
    )

    with pytest.warns(warning_type, match=warning_message):
        a = client.get_segment_efforts(**params)
        next(a)


def test_get_segment_efforts(client, mock_strava_api):
    """Test that endpoint returns data as expected."""
    mock_strava_api.get("/segment_efforts", n_results=4)

    efforts = list(
        client.get_segment_efforts(segment_id=2345, athlete_id=12345)
    )

    assert len(efforts) == 4
    assert efforts[0].name == "Alpe d'Huez"


def test_get_activities_paged(mock_strava_api, client):
    for i in range(1, 4):
        params = {"page": i, "per_page": 200}
        mock_strava_api.get(
            "/athlete/activities",
            response_update={"id": i},
            n_results=(200 if i < 3 else 100),
            match=[matchers.query_param_matcher(params)],
        )
    activity_list = list(client.get_activities())
    assert len(activity_list) == 500
    assert activity_list[0].id == 1
    assert activity_list[400].id == 3


@responses.activate
def test_upload_activity_photo_works():
    """
    Test uploading an activity with a photo.

    The pre-signed photo URL points at a third-party host, so it must never
    receive the Strava access token. This is why the token is set per
    request instead of on the session (see issue #733).
    """

    client = Client(access_token="token123")

    strava_pre_signed_uri = "https://strava-photo-uploads-prod.s3-accelerate.amazonaws.com/12345.jpg"
    photo_bytes = b"photo_data"
    photo_metadata_header = {
        "Content-Type": "image/jpeg",
        "Expect": "100-continue",
        "Host": "strava-photo-uploads-prod.s3-accelerate.amazonaws.com",
    }
    activity_upload_response = {
        "id": 12345,
        "external_id": "external_id",
        "error": None,
        "status": "Your activity is ready.",
        "activity_id": 12345,
        "photo_metadata": [
            {
                "uri": strava_pre_signed_uri,
                "header": photo_metadata_header,
                "method": "PUT",
                "max_size": 1600,
            }
        ],
    }
    with responses.RequestsMock(
        assert_all_requests_are_fired=True
    ) as _responses:
        _responses.add(
            responses.PUT,
            "https://strava-photo-uploads-prod.s3-accelerate.amazonaws.com/12345.jpg",
            status=200,
        )

        _responses.add(
            responses.GET,
            "https://www.strava.com/api/v3/uploads/12345",
            status=200,
            json=activity_upload_response,
        )

        activity_uploader = ActivityUploader(
            client, response=activity_upload_response
        )

        activity_uploader.upload_photo(photo=photo_bytes)

        photo_request = _responses.calls[-1].request
        assert photo_request.url == strava_pre_signed_uri
        assert "Authorization" not in photo_request.headers


def test_upload_activity_photo_fail_type_error(client):
    activity_uploader = ActivityUploader(client, response={})

    with pytest.raises(ActivityPhotoUploadFailed) as error:
        activity_uploader.upload_photo(photo="photo_str")

    assert str(error.value) == "Photo must be bytes type"


@mock.patch("stravalib.client.ActivityUploader.poll")
def test_upload_activity_photo_fail_activity_upload_not_complete(client):
    activity_upload_response = {
        "id": 1234578,
        "external_id": "external_id",
        "error": None,
        "status": "Your activity is being processed.",
    }
    activity_uploader = ActivityUploader(
        client, response=activity_upload_response
    )

    with pytest.raises(ActivityPhotoUploadFailed) as error:
        activity_uploader.upload_photo(photo=b"photo_bytes")

    assert str(error.value) == "Activity upload not complete"


@pytest.mark.parametrize("photo_metadata", (None, [], [{}]))
@mock.patch("stravalib.client.ActivityUploader.poll")
def test_upload_activity_photo_fail_not_supported(client, photo_metadata):
    activity_upload_response = {
        "id": 1234578,
        "external_id": "external_id",
        "error": None,
        "status": "Your activity is ready.",
        "activity_id": 1234578,
        "photo_metadata": photo_metadata,
    }

    activity_uploader = ActivityUploader(
        client, response=activity_upload_response
    )

    with pytest.raises(ActivityPhotoUploadFailed) as error:
        activity_uploader.upload_photo(photo=b"photo_bytes")

    assert str(error.value) == "Photo upload not supported"


def test_get_activity_comments(mock_strava_api, client):
    mock_strava_api.get(
        "/activities/{id}/comments",
        response_update={"text": "foo"},
        n_results=2,
    )
    comment_list = list(
        client.get_activity_comments(42)
    )  # no idea what the markdown param is supposed to do
    assert len(comment_list) == 2
    assert comment_list[0].text == "foo"


def test_explore_segments(mock_strava_api, client):
    # TODO parameterize test with multiple inputs
    # It is hard to patch the response for this one, since the
    # endpoint returns a nested list of segments.
    mock_strava_api.get("/segments/explore")
    segment_list = client.explore_segments((1, 2, 3, 4))
    assert len(segment_list) == 1
    assert segment_list[0].name == "Hawk Hill"


def test_explore_segments_restricted_warning(mock_strava_api, client):
    """Strava limited this endpoint to the Extended Access Tier on
    September 1, 2026. The method still works for an application in that
    tier, so the warning is a FutureWarning."""

    mock_strava_api.get("/segments/explore")

    with pytest.warns(
        FutureWarning,
        match=(
            '"explore_segments" method uses a Strava API endpoint that Strava '
            "restricted to the Extended Access Tier on September 1, 2026. "
            r"Calls from an application in the Standard Tier fail\."
        ),
    ):
        client.explore_segments((1, 2, 3, 4))


def test_explore_segments_invalid_bounds(client, recwarn):
    """Invalid input is rejected before the endpoint warning fires, and the
    error message shows the bounds the caller passed."""

    with pytest.raises(
        ValueError, match=r"Invalid bounds specified: \(1, 2, 3\)"
    ):
        client.explore_segments((1, 2, 3))

    assert not [w for w in recwarn if w.category is FutureWarning]


def test_get_activity_kudos(mock_strava_api, client):
    mock_strava_api.get(
        "/activities/{id}/kudos",
        response_update={"lastname": "Doe"},
        n_results=2,
    )
    kudoer_list = list(client.get_activity_kudos(42))
    assert isinstance(kudoer_list[0], SummaryAthlete)
    assert len(kudoer_list) == 2
    assert kudoer_list[0].lastname == "Doe"


@patch("stravalib.protocol.ApiV3.exchange_code_for_token")
def test_exchange_code_for_token_athlete(
    mock_protocol_exchange_code, client, raw_exchange_response
):
    """If a user requests athlete data, then it should be returned as a
    SummaryAthlete object."""
    mock_protocol_exchange_code.return_value = raw_exchange_response

    access_info, summary_athlete = client.exchange_code_for_token(
        client_id=123,
        client_secret="secret",
        code="temp_code",
        return_athlete=True,
    )

    assert access_info["access_token"] == "123456"
    assert summary_athlete.firstname == "Foo"


@patch("stravalib.protocol.ApiV3.exchange_code_for_token")
def test_exchange_code_for_token_missing_athlete(
    mock_protocol_exchange_code, client, raw_exchange_response
):
    """If athlete=True but Strava modifies the api response and athlete return
    is None client should only return AccessInfo object"""
    mock_protocol_exchange_code.return_value = (raw_exchange_response[0], None)
    access_info, athlete = client.exchange_code_for_token(
        client_id=123,
        client_secret="secret",
        code="temp_code",
        return_athlete=True,
    )

    assert athlete is None
    assert access_info["access_token"] == "123456"


@patch("stravalib.protocol.ApiV3.exchange_code_for_token")
def test_exchange_code_for_token_no_athlete(
    mock_protocol_exchange_code, client, raw_exchange_response
):
    """When athlete isn't True, only return AccessInfo Typed Dict."""
    mock_protocol_exchange_code.return_value = raw_exchange_response

    access_info = client.exchange_code_for_token(
        client_id=123,
        client_secret="secret",
        code="temp_code",
        return_athlete=False,
    )

    assert (
        access_info["access_token"] == raw_exchange_response[0]["access_token"]
    )
    assert isinstance(access_info, dict)


def test_inactive_application(mock_strava_api, client):
    """An inactive app should raise a fault that says how to fix it."""
    mock_strava_api.get(
        "/athlete",
        status=403,
        json={
            "message": "Forbidden",
            "errors": [
                {
                    "resource": "Application",
                    "field": "Status",
                    "code": "Inactive",
                }
            ],
        },
    )
    with pytest.raises(ApplicationInactive) as error:
        client.get_athlete()

    assert "https://www.strava.com/settings/api" in str(error.value)
