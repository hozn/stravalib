from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import stravalib.unit_helper as uh
from stravalib import model
from stravalib.model import (
    ActivityPhoto,
    ActivityTotals,
    AthletePrEffort,
    AthleteSegmentStats,
    AthleteStats,
    BaseEffort,
    DetailedActivity,
    Distance,
    Duration,
    Lap,
    LatLon,
    Route,
    Segment,
    SegmentEffort,
    SegmentExplorerResult,
    Split,
    SubscriptionCallback,
    SummaryActivity,
    SummarySegmentEffort,
    Timezone,
    Velocity,
    naive_datetime,
)
from stravalib.tests import TestBase


@pytest.mark.parametrize(
    "model_class,raw,expected_value",
    (
        (
            DetailedActivity,
            {"start_latlng": []},
            None,
        ),
        (
            DetailedActivity,
            {"end_latlng": []},
            None,
        ),
        (
            DetailedActivity,
            {"end_latlng": "5.4,4.3"},
            LatLon([5.4, 4.3]),
        ),
        (
            DetailedActivity,
            {"start_latlng": "5.4,4.3"},
            LatLon([5.4, 4.3]),
        ),
        (DetailedActivity, {"start_latlng": []}, None),
        (Segment, {"start_latlng": []}, None),
        (SegmentExplorerResult, {"start_latlng": []}, None),
        (ActivityPhoto, {"location": []}, None),
        # TODO re-add this Activity test when custom types are implemented
        # (DetailedActivity, {"timezone": "foobar"}, None),
        (
            DetailedActivity,
            {"start_date_local": "2023-01-17T11:06:07Z"},
            datetime(2023, 1, 17, 11, 6, 7),
        ),
        (
            BaseEffort,
            {"start_date_local": "2023-01-17T11:06:07Z"},
            datetime(2023, 1, 17, 11, 6, 7),
        ),
        (
            Lap,
            {"start_date_local": "2023-01-17T11:06:07Z"},
            datetime(2023, 1, 17, 11, 6, 7),
        ),
        (
            SummarySegmentEffort,
            {"start_date_local": "2023-01-17T11:06:07Z"},
            datetime(2023, 1, 17, 11, 6, 7),
        ),
        (
            SegmentEffort,
            {"start_date_local": "2023-01-17T11:06:07Z"},
            datetime(2023, 1, 17, 11, 6, 7),
        ),
    ),
)
def test_deserialization_edge_cases(model_class, raw, expected_value):
    obj = model_class.model_validate(raw)
    assert getattr(obj, list(raw.keys())[0]) == expected_value


@pytest.mark.parametrize(
    "model_class,raw,parsed_attr,expected_parsed_attr_value",
    (
        (SummarySegmentEffort, {"pr_activity_id": 42}, "activity_id", 42),
        (SummarySegmentEffort, {"activity_id": 42}, "activity_id", 42),
        (
            SummarySegmentEffort,
            {"pr_elapsed_time": 42},
            "elapsed_time",
            42,
        ),
        (
            SummarySegmentEffort,
            {"elapsed_time": 42},
            "elapsed_time",
            42,
        ),
        (AthletePrEffort, {"pr_activity_id": 42}, "activity_id", 42),
        (AthletePrEffort, {"activity_id": 42}, "activity_id", 42),
        (
            AthletePrEffort,
            {"pr_elapsed_time": 42},
            "elapsed_time",
            42,
        ),
        (
            AthletePrEffort,
            {"elapsed_time": 42},
            "elapsed_time",
            42,
        ),
    ),
)
def test_strava_api_field_name_inconsistencies(
    model_class, raw, parsed_attr, expected_parsed_attr_value
):
    obj = model_class.model_validate(raw)
    assert getattr(obj, parsed_attr) == expected_parsed_attr_value


def test_subscription_callback_field_names():
    sub_callback_raw = {
        "hub.mode": "subscribe",
        "hub.verify_token": "STRAVA",
        "hub.challenge": "15f7d1a91c1f40f8a748fd134752feb3",
    }
    sub_callback = SubscriptionCallback.model_validate(sub_callback_raw)
    assert sub_callback.hub_mode == "subscribe"
    assert sub_callback.hub_verify_token == "STRAVA"


@pytest.mark.parametrize(
    "klass,attr,given_type,expected_type",
    (
        (DetailedActivity, "sport_type", "Run", "Run"),
        (DetailedActivity, "sport_type", "FooBar", "Workout"),
        (DetailedActivity, "type", "Run", "Run"),
        (DetailedActivity, "type", "FooBar", "Workout"),
        (Segment, "activity_type", "Run", "Run"),
        (Segment, "activity_type", "FooBar", "Workout"),
    ),
)
def test_relaxed_activity_type_validation(
    klass, attr, given_type, expected_type
):
    obj = klass.model_validate({attr: given_type})
    assert getattr(obj, attr) == expected_type


@pytest.mark.parametrize(
    "klass,given_tags,expected_tags,expect_warning",
    (
        (SummaryActivity, None, None, False),
        (SummaryActivity, [], [], False),
        (
            SummaryActivity,
            ["WithPet", "Commute"],
            ["WithPet", "Commute"],
            False,
        ),
        (SummaryActivity, ["Indoor"], [], True),
        (DetailedActivity, ["Indoor", "Recovery"], ["Recovery"], True),
    ),
)
def test_relaxed_activity_tags_validation(
    klass, given_tags, expected_tags, expect_warning, caplog
):
    obj = klass.model_validate({"tags": given_tags})
    assert obj.tags == expected_tags
    assert ("Unexpected activity tags" in caplog.text) == expect_warning


@pytest.mark.parametrize(
    "a_attr,a_value,b_attr,b_value,expected_attr_equality",
    (
        ("type", "Run", "type", "Run", True),
        ("type", "Run", "type", "Ride", False),
        ("type", "Run", "id", 42, False),
        ("sport_type", "Run", "sport_type", "Run", True),
        ("sport_type", "Run", "sport_type", "Ride", False),
        ("sport_type", "Run", "id", 42, False),
    ),
)
def test_relaxed_activity_type_equality(
    a_attr, a_value, b_attr, b_value, expected_attr_equality
):
    a = SummaryActivity.model_validate({a_attr: a_value})
    b = SummaryActivity.model_validate({b_attr: b_value})
    assert (getattr(a, a_attr) == getattr(b, b_attr)) == expected_attr_equality


@pytest.mark.parametrize(
    "model_type,attr,expected_base_type,expected_extended_type",
    (
        (ActivityTotals, "distance", float, Distance),
        (ActivityTotals, "elevation_gain", float, Distance),
        (ActivityTotals, "elapsed_time", int, Duration),
        (ActivityTotals, "moving_time", int, Duration),
        (AthleteStats, "biggest_ride_distance", float, Distance),
        (AthleteStats, "biggest_climb_elevation_gain", float, Distance),
        (Lap, "distance", float, Distance),
        (Lap, "total_elevation_gain", float, Distance),
        (Lap, "average_speed", float, Velocity),
        (Lap, "max_speed", float, Velocity),
        (Lap, "elapsed_time", int, Duration),
        (Lap, "moving_time", int, Duration),
        (Split, "distance", float, Distance),
        (Split, "elevation_difference", float, Distance),
        (Split, "average_speed", float, Velocity),
        (Split, "average_grade_adjusted_speed", float, Velocity),
        (Split, "elapsed_time", int, Duration),
        (Split, "moving_time", int, Duration),
        (SegmentExplorerResult, "elev_difference", float, Distance),
        (SegmentExplorerResult, "distance", float, Distance),
        (AthleteSegmentStats, "distance", float, Distance),
        (AthleteSegmentStats, "elapsed_time", int, Duration),
        (AthletePrEffort, "distance", float, Distance),
        (AthletePrEffort, "pr_elapsed_time", int, Duration),
        (Segment, "distance", float, Distance),
        (Segment, "elevation_high", float, Distance),
        (Segment, "elevation_low", float, Distance),
        (Segment, "total_elevation_gain", float, Distance),
        (BaseEffort, "distance", float, Distance),
        (BaseEffort, "elapsed_time", int, Duration),
        (BaseEffort, "moving_time", int, Duration),
        (DetailedActivity, "distance", float, Distance),
        (DetailedActivity, "timezone", str, Timezone),
        (DetailedActivity, "total_elevation_gain", float, Distance),
        (DetailedActivity, "average_speed", float, Velocity),
        (DetailedActivity, "max_speed", float, Velocity),
        (DetailedActivity, "elapsed_time", int, Duration),
        (DetailedActivity, "moving_time", int, Duration),
        (Route, "distance", float, Distance),
        (Route, "elevation_gain", float, Distance),
    ),
)
def test_extended_types(
    model_type, attr, expected_base_type, expected_extended_type
):
    test_value = "Europe/Amsterdam" if expected_base_type == str else 42
    obj = model_type.model_validate(dict(**{attr: test_value}))
    assert isinstance(getattr(obj, attr), expected_base_type)
    assert isinstance(getattr(obj, attr), expected_extended_type)


@pytest.mark.parametrize(
    "model_type,attr,extended_attr,expected_base_value,expected_extended_value",
    (
        (
            ActivityTotals,
            "elapsed_time",
            "timedelta",
            42,
            timedelta(seconds=42),
        ),
        (ActivityTotals, "distance", "quantity", 42, uh.meters(42)),
        (Lap, "average_speed", "quantity", 42, uh.meters_per_second(42)),
    ),
)
def test_extended_types_values(
    model_type,
    attr,
    extended_attr,
    expected_base_value,
    expected_extended_value,
):
    obj = model_type.model_validate(dict(**{attr: 42}))
    base_attr = getattr(obj, attr)
    extended_attr = getattr(base_attr, extended_attr)()
    assert base_attr == expected_base_value
    assert extended_attr == expected_extended_value


@pytest.mark.parametrize(
    "arg,expected_value",
    (
        ("Invalid/Timezone", None),
        ("(GMT+00:00) Invalid/Timezone", None),
        ("Europe/Amsterdam", ZoneInfo("Europe/Amsterdam")),
        ("(GMT+01:00) Europe/Amsterdam", ZoneInfo("Europe/Amsterdam")),
    ),
)
def test_timezone(arg, expected_value):
    tz = Timezone(arg)
    assert tz.timezone() == expected_value


class ModelTest(TestBase):
    def setUp(self):
        super().setUp()

    def test_entity_collections(self) -> None:
        """Test that club information parsed from the API in a dict format can
        be correctly ingested into the Athlete model.

        Notes
        -----
        In Pydantic 2.x we use `model_validate` instead of `parse_object`.
        Model_Validate always returns a new model. In this test we
        instantiate a new instance a when calling `model_validate` aligning with
        Pydantic's immutability approach.

        """

        d = {
            "clubs": [
                {"resource_state": 2, "id": 7, "name": "Team Roaring Mouse"},
                {"resource_state": 2, "id": 1, "name": "Team Strava Cycling"},
                {
                    "resource_state": 2,
                    "id": 34444,
                    "name": "Team Strava Cyclocross",
                },
            ]
        }
        a = model.DetailedAthlete.model_validate(d)

        self.assertEqual(3, len(a.clubs))
        self.assertEqual("Team Roaring Mouse", a.clubs[0].name)

    def test_subscription_deser(self):
        d = {
            "id": 1,
            "object_type": "activity",
            "aspect_type": "create",
            "callback_url": "http://you.com/callback/",
            "created_at": "2015-04-29T18:11:09.400558047-07:00",
            "updated_at": "2015-04-29T18:11:09.400558047-07:00",
        }
        sub = model.Subscription.model_validate(d)
        self.assertEqual(d["id"], sub.id)

    def test_subscription_update_deser(self):
        d = {
            "subscription_id": "1",
            "owner_id": 13408,
            "object_id": 12312312312,
            "object_type": "activity",
            "aspect_type": "create",
            "event_time": 1297286541,
        }
        subupd = model.SubscriptionUpdate.model_validate(d)
        self.assertEqual(
            "2011-02-09 21:22:21",
            subupd.event_time.strftime("%Y-%m-%d %H:%M:%S"),
        )


# Test cases for the naive_datetime function
@pytest.mark.parametrize(
    "input_value, expected_output, exception",
    [
        (0, datetime(1970, 1, 1), None),
        ("2024-04-28T12:00:00Z", datetime(2024, 4, 28, 12, 0), None),
        (
            int(datetime(2022, 4, 28, 12, 0, tzinfo=timezone.utc).timestamp()),
            datetime(2022, 4, 28, 12, 0),
            None,
        ),
        (
            str(
                int(
                    datetime(
                        2022, 4, 28, 12, 0, tzinfo=timezone.utc
                    ).timestamp()
                )
            ),
            datetime(2022, 4, 28, 12, 0),
            None,
        ),
        (
            datetime(2024, 4, 28, 12, 0, tzinfo=timezone.utc),
            datetime(2024, 4, 28, 12, 0),
            None,
        ),
        (
            "April 28, 2024 12:00 PM UTC",
            datetime(2024, 4, 28, 12, 0),
            None,
        ),
        ("Foo", None, ValueError),
        ({"foo": 42}, None, ValueError),
        (None, None, None),
    ],
)
def test_naive_datetime(input_value, expected_output, exception):
    """Make sure our datetime parses properly reformats dates
    in various formats. This test is important given the pydantic
    `parse_datetime` method was removed in 2.x
    # https://docs.pydantic.dev/1.10/usage/types/#datetime-types
    Values
    1. date time as a formatted string
    2. datetime as a UNIX or POSIX format
    """
    if exception:
        with pytest.raises(exception):
            naive_datetime(input_value)
    else:
        assert naive_datetime(input_value) == expected_output
