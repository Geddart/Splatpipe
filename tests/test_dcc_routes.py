"""Tests for the DCC bridge HTTP endpoints.

These lock in the round-trip behavior verified manually via 3dsmax-mcp +
blender-mcp during the v0.6.2 / v0.6.3 release cycle. Without these tests,
the Stand-Up Parent compose math could regress silently.

Coverage:
  * GET  /dcc/manifest          — shape + LOD discovery + COLMAP detection
  * GET  /dcc/splat.ply         — 200 with content + 404 when missing
  * POST /dcc/import-camera     — JSON happy path (playcanvas_displayed)
  * POST /dcc/import-camera     — coord_frame=ply_native applies 180°X flip
  * POST /dcc/import-camera     — bad coord_frame -> 400, empty frames -> 400
  * POST /dcc/import-camera     — appends rather than replaces existing paths
"""

from __future__ import annotations

import pytest
import tomli_w
from starlette.testclient import TestClient

from splatpipe.core.project import Project


@pytest.fixture
def dcc_env(tmp_path, monkeypatch):
    """Set up a project with at least one reviewed PLY for DCC tests."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    toml_path = tmp_path / "defaults.toml"
    config = {
        "tools": {"postshot": "", "lichtfeld_studio": "", "colmap": "",
                  "splat_transform": "", "supersplat_url": ""},
        "colmap_clean": {"outlier_threshold_auto": True,
                         "outlier_threshold_fixed": 100.0,
                         "outlier_percentile": 0.99,
                         "outlier_multiplier": 2.5,
                         "kdtree_threshold": 0.001,
                         "coordinate_transform": [1, 0, 0, 0, 0, -1, 0, 1, 0]},
        "postshot": {"profile": "Splat3", "downsample": True,
                     "max_image_size": 3840, "anti_aliasing": False,
                     "create_sky_model": False, "train_steps_limit": 0,
                     "login": "", "password": ""},
        "lichtfeld": {"strategy": "mcmc", "iterations": 30000},
        "paths": {"projects_root": str(projects_root)},
    }
    with open(toml_path, "wb") as f:
        tomli_w.dump(config, f)
    monkeypatch.setattr("splatpipe.core.config.DEFAULTS_PATH", toml_path)

    proj_dir = projects_root / "DccTestProject"
    project = Project.create(proj_dir, "DccTestProject")

    # Drop a fake reviewed PLY so /dcc/splat.ply has something to serve.
    review_dir = proj_dir / "04_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    fake_ply = review_dir / "lod0_reviewed.ply"
    fake_ply.write_bytes(b"ply\nformat ascii 1.0\nelement vertex 0\nend_header\n")

    from splatpipe.web.app import app
    client = TestClient(app)
    yield {"client": client, "project": project, "proj_dir": proj_dir,
           "fake_ply": fake_ply}


# --- /dcc/manifest --------------------------------------------------------


class TestManifest:
    def test_manifest_returns_expected_shape(self, dcc_env):
        proj_path = str(dcc_env["proj_dir"])
        r = dcc_env["client"].get(f"/projects/{proj_path}/dcc/manifest")
        assert r.status_code == 200
        m = r.json()
        assert m["project_name"] == "DccTestProject"
        assert m["coord_frame_contract"] == "playcanvas_displayed"
        assert m["fps"] == 24
        assert m["frame_range"]["start"] == 1
        assert m["frame_range"]["end"] == 240
        # The fake PLY we wrote should show up.
        assert len(m["available_lods"]) >= 1
        assert m["available_lods"][0]["lod_index"] == 0
        assert m["splat_full_url"].endswith("/dcc/splat.ply?lod=0")
        assert m["import_camera_url"].endswith("/dcc/import-camera")

    def test_manifest_lists_existing_paths(self, dcc_env):
        # Seed a path via the DCC import endpoint so we exercise the round-trip
        # surface too.
        proj_path = str(dcc_env["proj_dir"])
        seed = {
            "name": "Seed",
            "fps": 24.0,
            "coord_frame": "playcanvas_displayed",
            "frames": [
                {"frame": 0, "pos": [0, 5, 0], "quat": [0, 0, 0, 1], "fov": 60},
                {"frame": 1, "pos": [1, 5, 0], "quat": [0, 0, 0, 1], "fov": 60},
            ],
        }
        r1 = dcc_env["client"].post(
            f"/projects/{proj_path}/dcc/import-camera", json=seed)
        assert r1.status_code == 200
        seeded_id = r1.json()["id"]

        r2 = dcc_env["client"].get(f"/projects/{proj_path}/dcc/manifest")
        names = [p["name"] for p in r2.json()["existing_paths"]]
        ids = [p["id"] for p in r2.json()["existing_paths"]]
        assert "Seed" in names
        assert seeded_id in ids


# --- /dcc/splat.ply -------------------------------------------------------


class TestSplatPly:
    def test_splat_ply_serves_lod0_when_present(self, dcc_env):
        proj_path = str(dcc_env["proj_dir"])
        r = dcc_env["client"].get(f"/projects/{proj_path}/dcc/splat.ply?lod=0")
        assert r.status_code == 200
        assert r.content.startswith(b"ply")
        assert r.headers.get("access-control-allow-origin") == "*"

    def test_splat_ply_falls_back_when_lod_missing(self, dcc_env):
        # We only have lod0, but the route should still serve something
        # rather than 404 when an out-of-range lod is requested.
        proj_path = str(dcc_env["proj_dir"])
        r = dcc_env["client"].get(f"/projects/{proj_path}/dcc/splat.ply?lod=99")
        assert r.status_code == 200
        assert r.content.startswith(b"ply")

    def test_splat_ply_404_when_no_review_plys(self, dcc_env):
        # Remove the only PLY and verify the route 404s cleanly.
        dcc_env["fake_ply"].unlink()
        proj_path = str(dcc_env["proj_dir"])
        r = dcc_env["client"].get(f"/projects/{proj_path}/dcc/splat.ply?lod=0")
        assert r.status_code == 404


# --- /dcc/import-camera ---------------------------------------------------


class TestImportCameraJson:
    def test_playcanvas_displayed_passes_through_unchanged(self, dcc_env):
        """The v0.6.2/v0.6.3 round-trip — frames sent in PC-displayed frame
        are stored byte-for-byte (no flip applied on the way in)."""
        proj_path = str(dcc_env["proj_dir"])
        payload = {
            "name": "Verify v0.6.3",
            "fps": 24.0,
            "coord_frame": "playcanvas_displayed",
            "smoothness": 1.0,
            "play_speed": 1.0,
            "loop": False,
            "frames": [
                {"frame": 0, "pos": [0.0, 5.0, 0.0],
                 "quat": [0.707107, 0, 0, 0.707107], "fov": 60.0},
                {"frame": 4, "pos": [0.0, 10.0, 10.0],
                 "quat": [0.382683, 0, 0, 0.92388], "fov": 60.0},
            ],
        }
        r = dcc_env["client"].post(
            f"/projects/{proj_path}/dcc/import-camera", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["keyframe_count"] == 2
        assert body["coord_frame_received"] == "playcanvas_displayed"

        # Reload the project and verify the keyframes landed unchanged.
        proj = Project(dcc_env["proj_dir"])
        paths = proj.scene_config.get("camera_paths") or []
        ours = next(p for p in paths if p["id"] == body["id"])
        assert len(ours["keyframes"]) == 2
        assert ours["keyframes"][0]["pos"] == [0.0, 5.0, 0.0]
        assert ours["keyframes"][1]["pos"] == [0.0, 10.0, 10.0]
        # t = frame / fps
        assert ours["keyframes"][0]["t"] == pytest.approx(0.0)
        assert ours["keyframes"][1]["t"] == pytest.approx(4.0 / 24.0)
        # DCC paths default to linear easing (the dense samples encode the curve)
        assert ours["keyframes"][0]["easing_out"] == "linear"

    def test_ply_native_applies_180x_flip(self, dcc_env):
        """When coord_frame=ply_native, the importer applies R_180X to the
        positions. So pos=(0, 5, 10) (PLY-native, Y-down) lands stored as
        (0, -5, -10) in PC-displayed frame."""
        proj_path = str(dcc_env["proj_dir"])
        payload = {
            "name": "PLY-Native Test",
            "fps": 24.0,
            "coord_frame": "ply_native",
            "frames": [
                {"frame": 0, "pos": [0.0, 5.0, 10.0],
                 "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
            ],
        }
        r = dcc_env["client"].post(
            f"/projects/{proj_path}/dcc/import-camera", json=payload)
        assert r.status_code == 200
        body = r.json()
        proj = Project(dcc_env["proj_dir"])
        ours = next(p for p in proj.scene_config["camera_paths"]
                    if p["id"] == body["id"])
        # R_180X: y → -y, z → -z
        assert ours["keyframes"][0]["pos"] == [0.0, -5.0, -10.0]

    def test_unknown_coord_frame_returns_400(self, dcc_env):
        proj_path = str(dcc_env["proj_dir"])
        payload = {
            "name": "Bad",
            "fps": 24.0,
            "coord_frame": "garbage_frame",
            "frames": [{"frame": 0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1], "fov": 60}],
        }
        r = dcc_env["client"].post(
            f"/projects/{proj_path}/dcc/import-camera", json=payload)
        assert r.status_code == 400

    def test_empty_frames_returns_400(self, dcc_env):
        proj_path = str(dcc_env["proj_dir"])
        payload = {"name": "Empty", "fps": 24.0,
                   "coord_frame": "playcanvas_displayed", "frames": []}
        r = dcc_env["client"].post(
            f"/projects/{proj_path}/dcc/import-camera", json=payload)
        assert r.status_code == 400

    def test_appends_rather_than_replaces(self, dcc_env):
        """Two POSTs should produce two distinct paths — D2/v0.5.0 had a
        regression where set_scene_config_section replaced the whole list."""
        proj_path = str(dcc_env["proj_dir"])

        def post_one(name):
            payload = {
                "name": name, "fps": 24.0,
                "coord_frame": "playcanvas_displayed",
                "frames": [{"frame": 0, "pos": [0, 0, 0],
                            "quat": [0, 0, 0, 1], "fov": 60}],
            }
            r = dcc_env["client"].post(
                f"/projects/{proj_path}/dcc/import-camera", json=payload)
            assert r.status_code == 200
            return r.json()["id"]

        id_a = post_one("First")
        id_b = post_one("Second")
        assert id_a != id_b
        proj = Project(dcc_env["proj_dir"])
        ids = [p["id"] for p in proj.scene_config["camera_paths"]]
        assert id_a in ids
        assert id_b in ids
