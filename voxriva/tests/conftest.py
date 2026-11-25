"""Unit suites are independent of HTTP application and database fixtures.

Application fixtures are registered only by integration/conftest.py.
"""


def pytest_collection_modifyitems(items):
    import pytest

    for item in items:
        if "/tests/integration/" in str(item.path):
            item.add_marker(pytest.mark.integration)
        elif "/tests/unit/" in str(item.path):
            item.add_marker(pytest.mark.unit)
