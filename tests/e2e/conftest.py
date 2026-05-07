"""Shared fixtures for the e2e tests."""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _silence_warnings():
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    yield
