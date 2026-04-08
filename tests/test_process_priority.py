from packrecorder.process_priority import set_current_process_below_normal


def test_set_priority_runs_without_error() -> None:
    assert isinstance(set_current_process_below_normal(), bool)
