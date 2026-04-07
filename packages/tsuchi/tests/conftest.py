"""Shared fixtures for Tsuchi tests."""

import pytest
from tsuchi.type_checker.types import reset_typevar_counter


@pytest.fixture(autouse=True)
def _reset_typevar():
    reset_typevar_counter()
