This is an example Flask application showing how you can use stravalib to help
with getting access tokens.

## Create A Virtualenv with venv

We'll assume you're using Python 3.

```bash
$ cd /path/to/stravalib
$ python3 -m venv env
$ source env/bin/activate
(env) $ pip install -e . --group dev
(env) $ pip install -r examples/strava-oauth/requirements.txt
```

## Create a Config File

Create a file -- for example `settings.cfg`
that contains your client id and secret in it:

```bash
(env) $ cd examples/strava-oauth/
(env) $ vi settings.cfg
```

```python
STRAVA_CLIENT_ID = 123
STRAVA_CLIENT_SECRET = "deadbeefdeadbeefdeadbeef"
```

## Run your flask server

Run the Flask server, specifying the path to this file in your `APP_SETTINGS`
environment var:

```
(env) $ APP_SETTINGS=settings.cfg python3 server.py
```
