"""Tests for splatpipe.core.path_io — camera path schema, mutate helper,
and importers (glTF + COLMAP)."""

import json
from pathlib import Path

import pytest

from splatpipe.core.path_io import (
    DEFAULT_EASING,
    DEFAULT_INTERPOLATION,
    PathDict,
    find_path,
    from_colmap,
    mutate_paths,
    new_path,
    remove_path,
    upsert_path,
)
from splatpipe.core.project import Project


# ---- new_path / find_path / upsert_path / remove_path ---------------------

def test_new_path_has_unique_id_and_defaults():
    p1 = new_path("foo")
    p2 = new_path("foo")
    assert p1["id"] != p2["id"]
    assert p1["name"] == "foo"
    assert p1["loop"] is False
    assert p1["interpolation"] == DEFAULT_INTERPOLATION
    assert p1["keyframes"] == []
    assert p1["id"].startswith("p_")


def test_find_path_returns_none_for_missing():
    assert find_path([], "nope") is None
    paths = [new_path("a"), new_path("b")]
    assert find_path(paths, paths[0]["id"]) is paths[0]
    assert find_path(paths, "nope") is None


def test_upsert_path_appends_or_replaces():
    paths: list[PathDict] = []
    p = new_path("a")
    upsert_path(paths, p)
    assert len(paths) == 1
    # Same id replaces
    p2 = {**p, "name": "renamed"}
    upsert_path(paths, p2)  # type: ignore[arg-type]
    assert len(paths) == 1
    assert paths[0]["name"] == "renamed"


def test_remove_path_filters_by_id():
    p1 = new_path("a")
    p2 = new_path("b")
    out = remove_path([p1, p2], p1["id"])
    assert len(out) == 1
    assert out[0]["id"] == p2["id"]


# ---- mutate_paths --------------------------------------------------------


def _make_project(tmp_path: Path) -> Project:
    """Bare minimum project for tests."""
    project = Project.create(
        tmp_path / "proj",
        name="testproj",
        trainer="passthrough",
    )
    return project


def test_mutate_paths_persists_via_set_scene_config_section(tmp_path):
    project = _make_project(tmp_path)
    p = new_path("first")

    def _add(paths):
        paths.append(p)
        return paths

    mutate_paths(project, _add)

    # Re-read fresh
    project2 = Project(project.root)
    saved = project2.scene_config.get("camera_paths") or []
    assert len(saved) == 1
    assert saved[0]["id"] == p["id"]


def test_mutate_paths_does_not_wipe_other_scene_config_sections(tmp_path):
    """Regression for D2: list replacement via set_scene_config_section must
    not affect sibling annotations."""
    project = _make_project(tmp_path)
    project.set_scene_config_section(
        "annotations", [{"id": "a1", "label": "1", "title": "x", "text": "", "pos": [0, 0, 0]}]
    )

    mutate_paths(project, lambda paths: paths + [new_path("p1")])

    fresh = Project(project.root)
    assert len(fresh.scene_config["annotations"]) == 1
    assert fresh.scene_config["annotations"][0]["id"] == "a1"
    assert len(fresh.scene_config["camera_paths"]) == 1


# ---- _migrate_state (annotation id backfill, B10) ----------------------


def test_migrate_state_assigns_ids_to_annotations_without_id():
    state = {
        "scene_config": {
            "annotations": [
                {"label": "1", "pos": [0, 0, 0]},      # no id → a1
                {"label": "2", "pos": [1, 0, 0], "id": "a3"},  # keep
                {"label": "3", "pos": [2, 0, 0]},      # no id → a2 (skips a3)
            ]
        }
    }
    changed = Project._migrate_state(state)
    assert changed is True
    ids = [a["id"] for a in state["scene_config"]["annotations"]]
    assert ids == ["a1", "a3", "a2"]


def test_migrate_state_idempotent_when_all_ids_present():
    state = {
        "scene_config": {
            "annotations": [
                {"id": "a1", "label": "1", "pos": [0, 0, 0]},
                {"id": "a2", "label": "2", "pos": [1, 0, 0]},
            ]
        }
    }
    assert Project._migrate_state(state) is False


def test_migrate_state_handles_no_annotations():
    assert Project._migrate_state({}) is False
    assert Project._migrate_state({"scene_config": {}}) is False
    assert Project._migrate_state({"scene_config": {"annotations": []}}) is False


# ---- from_colmap error handling (D7) ----------------------------------


def test_from_colmap_raises_friendly_error_when_dir_missing(tmp_path):
    missing = tmp_path / "no_such_dir"
    with pytest.raises(FileNotFoundError) as excinfo:
        from_colmap(missing)
    msg = str(excinfo.value)
    assert "passthrough" in msg.lower() or "colmap" in msg.lower()


def test_from_colmap_raises_when_dir_exists_but_no_files(tmp_path):
    empty = tmp_path / "empty_colmap"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        from_colmap(empty)


# ---- schema round-trip via JSON --------------------------------------


def test_path_dict_round_trips_through_json():
    p = new_path("x")
    p["keyframes"] = [
        {
            "t": 0.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1], "fov": 60.0,
            "easing_out": DEFAULT_EASING, "hold_s": 0.0, "annotation_id": None,
        },
        {
            "t": 2.5, "pos": [1, 2, 3], "quat": [0, 0.7071, 0, 0.7071],
            "fov": 75.0, "easing_out": "linear", "hold_s": 1.0,
            "annotation_id": "a1",
        },
    ]
    blob = json.dumps(p)
    reloaded = json.loads(blob)
    assert reloaded == p
