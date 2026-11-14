.. _overview:

Usage Overview
**************

The :class:`stravalib.client.Client` class exposes methods that loosely correspond
with the REST methods exposed by the Strava API.

Retrieving Single Entities
==========================

The simplest case are the client methods that return single entities. The entity object
types are instances of :mod:`stravalib.model` classes. For example::

   client = Client(access_token=JOHNS_ACCESS_TOKEN)
   athlete = client.get_athlete() # Get John's full athlete record
   print("Hello, {}. I know your email is {}".format(athlete.firstname, athlete.email))
   # "Hello, John.  I know your email is john@example.com"


Retrieving Entity Result Sets
=============================

A number of Strava API endpoints return paged results.  The stravalib library abstracts over
the paging to provide an iterator that will iterate over the entire resultset, fetching 200-page
result sets under the hood.

This capability is provided by the :class:`stravalib.client.BatchedResultsIterator` class.  If
you only wish to fetch a few objects, you can specify a limit in the method call or set the limit
on the resulting iterator.::

   activities = client.get_activities(limit=10)
   assert len(list(activities)) == 10

   # or:
   activities = client.get_activities()
   activities.limit = 10
   assert len(list(activities)) == 10

Note that setting the limit on the iterator is the only option when you are using the collection
attributes on entities.::

   activity = client.get_activity(activity_id)
   comments = activity.comments
   comments.limit = 1
   assert len(list(comments)) == 1


Attribute Types and Units
=========================

Many of the attributes in the Strava API are either temporal (or interval) types or
quantities that have implicit units associated with them. In both cases, richer python
types than the simple string or numeric values that the Strava REST API returns can be
accessed as follows:

Date/Time Types
---------------

The date+time responses are encoded as python native :class:`datetime.datetime`
objects.::

   a = client.get_activity(96089609)
   print(a.start_date)
   # 2013-11-17 16:00:00+00:00

Date values which have no time component are encoded as python native
:class:`datetime.date` objects.::

   me = client.get_athlete()
   print(me.dateofbirth)
   # 2010-12-26

Interval/duration values are given in seconds by default. You can use the
``timedelta()`` accessor to get :class:`datetime.timedelta` objects, which allows
them to be added to datetime objects, etc.::

   a = client.get_activity(96089609)
   print(a.elapsed_time)
   # 38700
   print(a.elapsed_time.timedelta())
   # 10:45:00


Quantities and Units
--------------------

Typically the units for quantity attributes returned by the Strava REST API are not
what people would actually want to see (e.g. meters-per-second instead of
kilometers-per-hour or miles-per-hour).

To facilitate working with these quantities, stravalib makes use of the
`pint library <https://pypi.org/project/Pint/>`_.  You can use the ``quantity()``
accessor to turn the "plain" ``int`` or ``float`` values into a
:class:`pint.Quantity` object.::

   activity = client.get_activity(96089609)
   print(activity.distance.quantity())
   # 22530.80 meter

Hmmm, meters.  Well, here in the US we like to see miles.  While you can certainly do
this using the Pint package, stravalib provides a preconfigured set of common units to
simplify matters.::

   from stravalib import unit_helper

   activity = client.get_activity(96089609)
   print(unit_helper.miles(activity.distance))
   # 14.00 mi

Of course, if you want to do something besides display those values, you'll likely
want a number.  You can directly access the 'magnitude' attribute of the
:class:`pint.Quantity` instance.::

   activity = client.get_activity(96089609)
   print(unit_helper.miles(activity.distance).magnitude)
   # 13.9999900581


Rate Limits
===========

Strava imposes rate limits on the usage of its API. This means that the number of
requests sent to Strava have an upper limit per 15 minutes and per day. These limits
are not fixed but depend on the "size" of the client app. Strava _may_ choose to
adjust rate limits for apps as they grow. [Learn more about rate limits here.](https://developers.strava.com/docs/rate-limits/)
You can see the limits set for your app at [your account's settings.](https://www.strava.com/settings/api)

When initializing a `stravalib.Client` instance, the default rate limiter allows requests until
the short - or daily limits are reached. Once limits are reached. the client object will wait until the end of
the 15-minute or day period.

In case you want to configure the limiter to throttle requests (i.e., making sure
the time between requests for the remaining period is evenly spread), you can
initialize the client object as::

   from stravalib.util.limiter import DefaultRateLimiter
    client = stravalib.Client(
        my_access_token, rate_limiter=DefaultRateLimiter(priority='medium')
    )


The ``low`` priority complies with the daily limit. The ``medium`` priority ensures that requests are throttled to comply with the
15-minute limit.

The built-in limiter considers the overall and non-upload quota families
separately and uses the longest applicable wait. Activity creation and file
uploads use only the overall quota; fetching upload status uses both.
Throttling happens after a response, before it is returned or an HTTP error
is raised. It does not retry requests or coordinate other clients sharing
the application's quota. A newly considered limit can therefore delay a
successful result or an error until that limit resets.

Custom callbacks still receive ``(response_headers, method)``. An override
of ``__call__`` keeps control of dispatch. Calling a limiter directly with
those two arguments provides no endpoint context: GET considers both quota
families, while other methods retain their overall-only behavior.
