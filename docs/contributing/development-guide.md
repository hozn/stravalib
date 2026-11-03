# Development Guide for Contributing to Stravalib

```{note}
 * Please make sure that you've read our [contributing guide](how-to-contribute.md)
before reading this guide.
* If you are looking for information on our package build structure and release workflow, please see our build and [release guide](build-release-guide)
```

The steps to get started with contributing to stravalib are below. To begin, fork and clone the [stravalib GitHub repository](https://github.com/stravalib/stravalib).

## Fork and clone the stravalib repository

### 1. Fork the repository on GitHub

To create your own copy of the stravalib repository on GitHub, navigate to the
[stravalib/stravalib](https://github.com/stravalib/stravalib) repository
and click the **Fork** button in the top-right corner of the page.

### 2. Clone your fork locally

Next, use `git clone` to create a local copy of your stravalib forked
repository on your local filesystem:

```bash
$ git clone git@github.com:your_name_here/stravalib.git
$ cd stravalib/
```

Once you have cloned your forked repository locally, you are ready to create a
development environment.

## Setup a local development environment

We suggest you create a virtual environment on your computer to work on
`stravalib`.

::::{tab-set}

::: {tab-item} venv
Follow these instructions if you prefer using `venv` to create virtual environments.

To begin, create a new virtual environment in the project directory.
This will create a local environment directory called `stravalib_env`:

```bash
$ python -m venv stravalib_env
```

Next, activate the environment.

On macOS and Linux:

```bash
$ source stravalib_dev_env/bin/activate
```

On Windows:

```bash
$ .\stravalib_dev_env\Scripts\activate
```
:::

::: {tab-item} Conda
If you prefer Conda for environment management, use the instructions below.
Anaconda and Miniconda are two commonly-used conda Python distributions.

If you are unsure of which distribution to use,
[we suggest miniconda](https://docs.conda.io/en/latest/miniconda.html) as it is
a lighter-weight installation.

To begin, create a new `conda` environment called `stravalib_dev`.

```bash
$ conda env create -f environment.yml
```

Next, activate the environment.

```
$ conda activate stravalib_dev
```
:::

::::

Once you have a virtual environment created, you are ready to install stravalib's package dependencies and the `stravalib` package in
 editable mode (`-e`). Editable mode allows you to update the package and test those updates in real-time.

```bash
# Install the package in editable model and test requirements
$ pip install -e . --group dev
```

If you also need to install dependencies for building docs, also run:
```bash
$ pip install --group docs
```

(ci_api_updates)=
## Architecture Overview

![Stravalib Architecture](../images/stravalib_architecture.png)

Stravalib contains the following main components:

At the core, a (pydantic) domain model is generated and updated by a bot via
pull requests. This model reflects the officially published API specification
by Strava and is stored in the module `strava_model.py`. This file should never
be edited manually. Instead, the stravalib bot will suggest changes to the
model through pull requests that can then be merged by stravalib maintainers.

The module `model.py` contains classes that inherit from the
official Strava domain model in `strava_model.py`. This module supports custom
typing, unit conversion, (de-)serialization behavior, and support for
undocumented Strava features.

The module `protocol.py` manages the sending of HTTP requests
to Strava and handling the received responses (including rate limiting).
It is used by methods in `client.py` to de-serialize raw response data into
the domain entities in `model.py`.

## Python support
We loosely follow the [Numpy guidelines defined in NEP 29](https://numpy.org/neps/nep-0029-deprecation_policy.html)
for Python version support. However, in some cases, we may decide to
support older versions of Python, following community demand.

## Code style, linting & typing

We use several tools to maintain consistent code formatting and adhere to the [Python Enhancement Protocol (PEP) 8](https://peps.python.org/pep-0008/) standards, which outline best practices for Python code readability and structure. Below are the primary tools configured for this project:

- [black](https://black.readthedocs.io/en/stable/): An auto-formatter that enforces consistent code style. Although Black’s default line length is 88 characters, we configure it to 79 characters to better align with [PEP 8 line width guidelines](https://peps.python.org/pep-0008/#maximum-line-length).
- [ruff](https://github.com/charliermarsh/ruff): A fast, all-in-one Python linter that covers many functions formerly provided by separate tools like `flake8` and `isort`. Ruff performs both linting and import sorting, identifying unused imports, variables, and other PEP 8 inconsistencies.
- [codespell](https://github.com/codespell-project/codespell): A spelling checker for code comments and documentation, helping to catch typos in Python, Markdown, and RST files.
- [blacken-docs](https://github.com/adamchainz/blacken-docs): A tool for applying Black’s formatting to Python code blocks, ensuring consistent code style in documentation.


### Pre-commit Hook Setup

For local development, we use [`pre-commit`](https://pre-commit.com/), which automatically runs each code format and linting tool configured in the `pre-commit-config.yaml` file. Once installed, `pre-commit` will execute each tool in the configuration file every time you make a commit.

With pre-commit hooks setup, here’s what happens when you make a new commit to our codebase:

1. **black**: Automatically formats code to meet style guidelines. If the formatting is incorrect, `black` will reformat it for you.
2. **ruff**: Runs linting checks and fixes minor issues automatically, including sorting imports.
3. **codespell**: Identifies typos in code comments and documentation. You will need to fix these manually.
4. **blacken-docs**: Blacken docs will format any code snippets provided in our documentation to match Black's guidelines above

If issues are found that cannot be automatically corrected, you’ll see a list of errors that need to be addressed before proceeding with your commit.

### Setup and run the pre-commit hooks

The configuration for all of the pre-commit hooks is found in the **.pre-commit-config.yaml**
file. To set up our pre-commit hooks locally:

1. First, make sure that pre-commit is installed. You can install pre-commit using `pip` or `pipx`.

```bash
$ pip install pre-commit
```

Next, install all of the hooks into your stravalib development environment.
```bash
$ pre-commit install
```

:::{tip}

You can run all pre-commit hooks locally without a commit by using:

```bash
$ pre-commit run --all-files
```

You can also run a single hook using the following:

```
# Only run ruff
# pre-commit run ruff
```
:::

### Pre-commit.ci bot

We use the `https://pre-commit.ci` bot, in addition to pre-commit in our local
build to manage pull requests. The configuration for this bot can be found
in the ci: section of the `pre-commit-config.yaml` file.
This bot can run all of the code format hooks on every pull request if it's set
to do so.

Currently, we have the bot set to run only when it's asked to run on a PR.
To call the bot on a pull request, add the text:

`pre-commit.ci run`

as a single-line comment in the pull request. The bot will automatically run
all of the hooks that it is configured to run.

```{tip}
If you have an open Pull Request but you need to make some changes locally,
and the bot has already run on your pull request and added a commit, you can
force push to the pull request to avoid multiple bot commits.

To do this:
* Do not pull down any changes from the pull request,
* Commit your changes locally,

When you are ready to push your local changes use:

`git push origin branch-name-here --force`

If you have not yet pulled down pre-commit bot's changes, this will
force the branch to be in the same commit state as your local branch.

```

### Typing using mypy

We use [mypy](https://mypy.readthedocs.io/) to ensure proper typing throughout our library. To run `mypy` across Python versions, use:

`nox -s mypy`

Similar to running tests, if you are missing a version of Python, `nox` will
skip that run and continue to the next version.

```bash

❯ nox -s mypy
nox > Running session mypy-3.11
nox > Missing interpreters will error by default on CI systems.
nox > Session mypy-3.11 skipped: Python interpreter 3.11 not found.
nox > Running session mypy-3.12
```

## Code format and syntax

If you are contributing code to `stravalib`, please be sure to follow PEP 8
syntax best practices.

### Docstrings

**All docstrings** should follow the
[numpy style guide](https://numpydoc.readthedocs.io/en/latest/format.html#docstring-standard).
All functions/classes/methods should have docstrings with a full description of
all arguments and return values.

```{warning}
This also will be updated once we implement a code styler
While the maximum line length for code is automatically set by *Black*,
docstrings must be formatted manually. To play nicely with Jupyter and IPython, **limit docstrings to 79 characters** per line.
```

## About the stravalib test suite

Stravalib has a set of unit and integration tests that can be run locally and that
also run in our CI infrastructure using GitHub Actions. To avoid direct API calls which require authentication,
when running our test suite, we have a mock fixture and and infrastructure setup.

### Unit and integration test suite

We have set up the test suite to run on the stravalib package as installed.
Thus, when running your tests, it is critical that you have a stravalib
development environment setup and activated with the stravalib package
installed from your fork using pip `pip install .`

You can run the tests using make as specified below. Note that when you run
the tests this way, they will run in a temporary environment to ensure that
they are running against the installed version of the package that you are working on.

To run the test suite across all Python versions that we support use:

```
nox -s tests
```

`nox -s tests` does a few things:

1. It creates a temporary directory called `tmp-test-dir-stravalib` in which your tests are run. We create this test directory to ensure that tests are being run against the installed version of stravalib (with the most recent local development changes as installed) rather than the flat files located in the GitHub repository.
2. It runs the tests and provides output (see below)
3. Finally it removes the temporary directory

To run tests for a specific Python version use:

`nox -s tests-python-version-here`.

For example, the command below runs our tests on Python 3.11 only.

```bash
nox -s tests-3.11
```


### Test code coverage

We use [pytest-cov](https://pytest-cov.readthedocs.io/en/latest/) to calculate
test coverage. When you run `nox -s tests` pytest-cov will provide you with
coverage outputs locally. You can ignore the returned values for any files in
the `test` directory.

Example output from `nox -s test`:

```bash
pytest --cov stravalib stravalib/tests/unit stravalib/tests/integration
=================================================== test session starts ===================================================
platform darwin -- Python 3.8.13, pytest-7.2.0, pluggy-1.0.0
rootdir: .../stravalib
plugins: cov-4.0.0
collected 105 items

stravalib/tests/unit/test_attributes.py ...............                                                             [ 14%]
stravalib/tests/unit/test_client_utils.py .......                                                                   [ 20%]
stravalib/tests/unit/test_limiter.py .............                                                                  [ 33%]
stravalib/tests/unit/test_model.py .......                                                                          [ 40%]
stravalib/tests/integration/test_client.py ...............................................................          [100%]

---------- coverage: platform darwin, python 3.8.13-final-0 ----------
Name                                                     Stmts   Miss  Cover
----------------------------------------------------------------------------
stravalib/__init__.py                                        2      0   100%
stravalib/_version.py                                        2      0   100%
stravalib/_version_generated.py                              2      0   100%
stravalib/attributes.py                                    170     19    89%
stravalib/client.py                                        439    180    59%
stravalib/exc.py                                            34      3    91%
stravalib/model.py                                         709    126    82%
stravalib/protocol.py                                      130     39    70%
stravalib/unit_helper.py                                     16      1    94%
stravalib/util/__init__.py                                   0      0   100%
stravalib/util/limiter.py                                  122     27    78%
----------------------------------------------------------------------------
TOTAL
```

### Code coverage reporting on pull requests with codecov

We use an integration with [codecov.io](https://about.codecov.io) to report test coverage
changes on every pull request. This report will appear in your pull request once
all of the GitHub action checks have run.

```{note}
The actual code coverage report is
uploaded on the GitHub action run on `ubuntu` and `Python 3.11`. When that step in the
actions completes, the report will be processed and returned to the pull request.
```

## Tests & the stravalib mock fixture

To run integration tests that ensure stravalib is interacting with API data correctly, Stravalib uses a mock object accessed through a
`pytest` fixture `stravalib.tests.integration.strava_api_stub.StravaAPIMock`
that is based on `responses.RequestsMock`.

This fixture adds a mock that prevents requests from being made to the Strava API.
Instead, it creates responses using the endpoint provided and the `swagger.json` file that is found both online and within the `stravalib/src/stravalib/tests/resources/` directory that are based on examples from the published Strava API
documentation.

:::{tip}
Example usages of this fixture can be found in the
{py:mod}`stravalib.tests.integration.test_client` module.
:::

:::{mermaid}

flowchart TD
    A["fab:fa-strava Stravalib Test Suite"] --> C["**mock_strava_api fixture** <br>(defined in conftest)"]
    C -- Creates instance of --> D["**StravaAPIMock** <br> strava_api_stub.py module <br> Inherits from responses.RequestsMock"]
    D -- Returns fake response data using: --> G["**swagger.json** <br>(local or online)"]
    style C color:#FFFFFF, stroke:#00C853, fill:#AA00FF
    style G color:#FFFFFF, fill:#d35400, stroke:#AA00FF
    style A color:#FFFFFF, fill:#d35400, stroke:#AA00FF
:::

### How the mock fixture works

The `stravalib` test suite is supported by the
{py:class}`stravalib.tests.integration.strava_api_stub.StravaAPIMock` mock
API object, which is used in most client GET method tests through a `pytest`
fixture.

The Strava API mock object:

1. **Matches Endpoints**: Attempts to match the endpoint being tested with
   a corresponding path in `swagger.json`, using either an online or local
   copy. This mock expects a relative URL that aligns with a path in the
   `swagger.json` file (e.g., `/activities/{Id}`) and includes the
   appropriate HTTP method and status code.

2. **Provides Example Responses**: Retrieves the example JSON response
   associated with the matched endpoint in `swagger.json` and uses it as
   the mock response body. The example response can be customized by
   using the `response_update` parameter, which accepts a dictionary of
   values to override fields in the default response. If the response is a
   JSON array, the `n_results` argument can specify how many objects to
   return.

If the object can find an endpoint match, it then returns the example JSON response
(or the updated response if you use the update parameter) to use in the test.

:::{tip}
The `swagger.json` file is an API specification document describing the
available endpoints in the Strava API, including methods, parameters, and
expected responses for each endpoint. It defines the API structure in JSON
format and includes example responses for testing. This file is used in
`stravalib`'s tests to mock API interactions and validate the expected
structure and content of responses.

The mock API object checks if `swagger.json` is accessible online; if not,
it uses a local version located in the `tests/resources` directory within
`stravalib`.
:::

### Mock fixture features

To call the mock fixture in a test, you

1. Create a new test and add the `mock_strava_api` fixture as an input to the test function.

The test below will try to access the `/athlete/activities`
Strava endpoint which returns an athlete's activities.
Here, the fixture will bypass trying to access the real online API. And instead, will find the `/athlete/activities`
endpoint in the Strava online or local `swagger.json` file.

When you call {py:func}`stravalib.client.Client.get_activities()`, the mocked endpoint will return the sample data provided in the `swagger.json` file.

```python
def test_example(mock_strava_api, client):
    """An example test"""

    mock_strava_api.get("/athlete/activities")
    activity_list = list(client.get_activities())
    assert len(activity_list) == 4
```

The mock fixture object provides parameters that allow you to modify a test.

Sometimes you may want to update the default example return data in the swagger.json file. This might happen if you want to intentionally "break" a test to ensure that the client call responds appropriately.

To modify the returned sample data use the `response_update`
parameter. Below you update the response id key to be another value.

```python
def test_example_test(mock_strava_api, client):
    """An example test"""
    mock_strava_api.get(
        "/athlete/activities",
        response_update={"id": 12345},
    )
    activity_list = list(client.get_activities())
```

You can also specify the number of results that you'd like to see in the mock output using the `n_results` parameters.

```python
def test_example_test(mock_strava_api, client):
    """An example test"""
    mock_strava_api.get(
        "/athlete/activities",
        response_update={"id": 12345},
        n_results=4,
    )
    activity_list = list(client.get_activities())
```

:::{tip}
Stravalib uses lazily loaded entities when returning results from
endpoint such as activities that may include multiple response objects in the return. As such, a mocked call to {py:func}`stravalib.client.Client.get_activities` will not actually initiate a get response
until you try to access the first object returned in the {py:class}`stravalib.client.BatchedResultsIterator` object.
:::

## Documentation

`Stravalib` documentation is created using `sphinx` and the
[`pydata_sphinx_theme`](https://pydata-sphinx-theme.readthedocs.io/en/stable/index.html) theme.
`Stravalib` documentation is hosted on [ReadtheDocs](https://readthedocs.org).

The final online build that you see on readthedocs happens on the readthedocs
website. Our continuous integration GitHub action only tests that the documentation
builds correctly. It also tests for broken links.

The readthedocs build is configured using the `.readthedocs.yml` file rather than
from within the readthedocs interface as recommended by the readthedocs website.

The badge below (also on our `README.md` file) tells you whether the
readthedocs build is passing or failing.

[![Documentation Status](https://readthedocs.org/projects/stravalib/badge/?version=latest)](https://stravalib.readthedocs.io/en/latest/?badge=latest)

Currently [@hozn](https://www.github.com/hozn), [@lwasser](https://www.github.com/lwasser) and [@jsamoocha](https://www.github.com/jsamoocha) have access to the readthedocs `stravalib`
documentation build

Online documentation will be updated on all merges to the main branch of
`stravalib`.

### Build documentation locally

To build the documentation, first activate your stravalib development
environment which has all of the packages required to build the documentation.
Then, use the command:

```bash
$ nox -s docs
```

This command:

- Builds documentation
- Builds `stravalib` API reference documentation using docstrings within the package
- Checks for broken links

After running `nox -s docs` you can view the built documentation in a web
browser locally by opening the following file on your computer:

```
/your-path-to-stravalib-dir/stravalib/docs/_build/html/index.html
```

You can also view any broken links in the output.txt file located here:

`/your-path-to-stravalib-dir/stravalib/docs/_build/linkcheck/output.txt`

### Build locally with a live server

We use `sphinx-autobuild` to build the documentation in a live web server.
This allows you to see your edits automatically as you are working on the
text files of the documentation. To run the live server use:

```bash
$ nox -s docs-live
```

```{note}
There is a quirk with autobuild where included files such as the CHANGELOG will
not update live in your local rendered build until you update content on a
file without included content.
```

### Stravalib API Documentation

The API reference can be found [here](reference).
The *autodoc* sphinx extension will automatically create pages for each
function/class/module listed there.

You can reference classes, functions, and modules from anywhere (including docstrings)
using
* <code>{py:func}\`package.module.function\`</code>,
* <code>{py:func}\`package.module.Class.method\`</code>,
* <code>{py:class}\`package.module.class\`</code>, or
* <code>{py:mod}\`package.module\`</code>.

Sphinx will create a link to the automatically generated page for that
function/class/module.

### About the documentation CI build

Once you create a pull request, GitHub actions will build the docs and
check for any syntax or url errors. Once the PR is approved and merged into the main branch of the `stravalib/stravalib`
repository, the docs will build and be [available at the readthedocs website](https://stravalib.readthedocs.io/en/latest/).

### Cleanup of documentation and package build files

To clean up all documentation build folders and files, run the following
command from the root of the `stravalib` directory:

```bash
$ nox -s clean-docs
```

To clean up build files such as the package **.whl**, and other temporary files
created when building `stravalib` distributions and running tests, run:

```bash
$ nox -s clean_build
```
