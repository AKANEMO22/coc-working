"""Levels must reflect normalized hiring evidence, not broad title matching."""

import pytest

from app.domains.candidate.context import job_levels


@pytest.mark.parametrize("record,expected", [
    ({"required_level": "Intern", "declared_levels": "Fresher, Intern", "min_years": 0}, ["Intern", "Fresher"]),
    ({"required_level": "Junior", "declared_levels": ["junior", "Junior"]}, ["Junior"]),
    ({"required_level": "Fresher", "job_title": "All level AI Engineer", "min_years": 0}, ["Fresher"]),
    ({"required_level": "Junior", "declared_levels": "Fresher, Intern", "min_years": 2}, []),
    ({"required_level": "Intern", "declared_levels": "Intern", "min_years": 2}, []),
    ({"required_level": "unknown", "declared_levels": "", "min_years": 0}, []),
])
def test_only_declared_consistent_levels_qualify(record, expected):
    assert job_levels(record) == expected
