from src import guards


def test_a_table_that_had_rows_and_now_has_none_is_reported():
    prev = {"gaez_grid": 222720, "dim_crop": 24, "terrain": 6}
    assert guards.dropped_to_zero({"gaez_grid": 0, "dim_crop": 24, "terrain": 6}, prev) == ["gaez_grid"]


def test_a_table_missing_from_the_new_run_counts_as_zero():
    assert guards.dropped_to_zero({"dim_crop": 24}, {"gaez_grid": 5, "dim_crop": 24}) == ["gaez_grid"]


def test_shrinking_or_growing_is_not_a_drop_to_zero():
    assert guards.dropped_to_zero({"a": 1, "b": 900}, {"a": 500, "b": 10}) == []


def test_a_table_that_was_already_empty_is_not_reported():
    assert guards.dropped_to_zero({"x": 0}, {"x": 0}) == []


def test_allow_lists_a_deliberately_empty_table():
    assert guards.dropped_to_zero({}, {"a": 3, "b": 4}, allow=["a"]) == ["b"]
    assert guards.dropped_to_zero({}, {"a": 3}, allow=("a",)) == []


def test_result_is_sorted_so_the_message_is_stable():
    assert guards.dropped_to_zero({}, {"zeta": 1, "alpha": 1}) == ["alpha", "zeta"]


def test_catalog_rows_with_and_without_a_previous_run():
    cat = {"datasets": {"gaez_grid": {"rows": 222720}, "terrain": {"rows": None}, "x": {}}}
    assert guards.rows_from_catalog(cat) == {"gaez_grid": 222720, "terrain": 0, "x": 0}
    assert guards.rows_from_catalog(None) == {} and guards.rows_from_catalog({}) == {}


def test_message_names_the_table_the_row_count_and_the_escape_hatch():
    m = guards.message(["gaez_grid"], {"gaez_grid": 222720}, "database")
    assert "gaez_grid" in m and "222,720" in m and "--allow-empty" in m and "pull_bronze.py" in m
