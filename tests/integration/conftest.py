"""Fixtures shared by integration suites; unit tests need no application database."""

from tests.support.administration import store as store
from tests.support.postgres import postgres_store as postgres_store
