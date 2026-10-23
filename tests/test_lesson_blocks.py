import pytest

from app.lesson_validation import can_fit_weekly_blocks


@pytest.mark.parametrize(
    ("runs", "count", "length", "expected"),
    [
        ([2, 1], 3, 2, True),  # a double plus the remaining single
        ([1, 1, 1], 3, 2, False),  # singles cannot masquerade as a double
        ([2, 2], 3, 2, True),
        ([2, 2], 4, 2, True),
        ([2], 3, 2, False),  # no reuse of a period for the remainder
        ([2, 2], 3, 3, False),  # a three-period block cannot cross lunch
        ([3, 1], 4, 3, True),
        ([], 1, 1, False),
        ([1] * 20, 20, 1, True),
        ([1] * 20, 2, 2, False),
    ],
)
def test_weekly_block_packing_preserves_counts_without_crossing_breaks(runs, count, length, expected):
    assert can_fit_weekly_blocks(runs, count, length) is expected
