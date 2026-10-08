"""Library grouping follows graph children while execution identities stay exact."""

import pytest

from obsidience.harness.knowledge import skills


# The temporary-observation callables (and their display-namespace exception)
# were retired with Immediate/Temporary Observations; grouping is the exact
# callable prefix for every Tool.
@pytest.mark.parametrize("name,expected", [
    ("observations.temporary.append", "observations.temporary"),
    ("example.deep.read", "example.deep"),
    ("other.temporary.append", "other.temporary"),
    ("observations.temporary_history.read", "observations.temporary_history"),
    ("observations.temporary.deep.read", "observations.temporary.deep"),
])
def test_display_namespace_is_the_exact_callable_prefix(name, expected):
    assert skills.callable_namespace(name) == expected
