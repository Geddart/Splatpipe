"""Tests for web route endpoints using FastAPI TestClient."""


import pytest
import tomli_w
from starlette.testclient import TestClient

from splatpipe.core.project import Project


@pytest.fixture
def web_env(tmp_path, monkeypatch):
    """Set up a temporary environment for web route tests.

    Creates a temporary defaults.toml with projects_root pointing to tmp_path,
    patches DEFAULTS_PATH, and creates a test project.
    """
    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    # Write temporary defaults.toml
    toml_path = tmp_path / "defaults.toml"
    config = {
        "tools": {
            "postshot": "",
            "lichtfeld_studio": "",
            "colmap": "",
            "splat_transform": "",
            "supersplat_url": "https://superspl.at/editor",
        },
        "colmap_clean": {
            "outlier_threshold_auto": True,
            "outlier_threshold_fixed": 100.0,
            "outlier_percentile": 0.99,
            "outlier_multiplier": 2.5,
            "kdtree_threshold": 0.001,
            "coordinate_transform": [1, 0, 0, 0, 0, -1, 0, 1, 0],
        },
        "postshot": {
            "profile": "Splat3",
            "downsample": True,
            "max_image_size": 3840,
            "anti_aliasing": False,
            "create_sky_model": False,
            "train_steps_limit": 0,
            "login": "",
            "password": "",
        },
        "lichtfeld": {"strategy": "mcmc", "iterations": 30000},
        "paths": {"projects_root": str(projects_root)},
    }
    with open(toml_path, "wb") as f:
        tomli_w.dump(config, f)

    monkeypatch.setattr("splatpipe.core.config.DEFAULTS_PATH", toml_path)

    # Create test project with COLMAP source dir
    proj_dir = projects_root / "TestProject"
    colmap_dir = tmp_path / "colmap_data"
    colmap_dir.mkdir()
    (colmap_dir / "cameras.txt").write_text("# 3 cameras\n")
    (colmap_dir / "images.txt").write_text("# 5 images\n")
    (colmap_dir / "points3D.txt").write_text("# 50 points\n")

    project = Project.create(
        proj_dir, "TestProject",
        colmap_source=str(colmap_dir),
    )

    from splatpipe.web.app import app
    client = TestClient(app)

    return {
        "client": client,
        "project": project,
        "projects_root": projects_root,
        "toml_path": toml_path,
        "colmap_dir": colmap_dir,
        "tmp_path": tmp_path,
    }


# --- Root / Index ---


class TestIndex:
    def test_index_redirects_to_projects(self, web_env):
        """Root URL redirects to project list when projects_root is set."""
        r = web_env["client"].get("/", follow_redirects=False)
        # Returns 200 (renders projects.html directly) or 303 redirect
        assert r.status_code in (200, 303)

    def test_index_no_projects_root(self, tmp_path, monkeypatch):
        """Root URL redirects to settings when projects_root not set."""
        toml_path = tmp_path / "defaults.toml"
        with open(toml_path, "wb") as f:
            tomli_w.dump({"tools": {}, "paths": {"projects_root": ""}}, f)
        monkeypatch.setattr("splatpipe.core.config.DEFAULTS_PATH", toml_path)

        from splatpipe.web.app import app
        client = TestClient(app)
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 303
        assert "/settings/" in r.headers.get("location", "")


# --- Projects routes ---


class TestProjectList:
    def test_project_list(self, web_env):
        """GET /projects/ returns 200."""
        r = web_env["client"].get("/projects/")
        assert r.status_code == 200
        assert "TestProject" in r.text


class TestProjectNew:
    def test_new_form(self, web_env):
        """GET /projects/new returns 200 with form."""
        r = web_env["client"].get("/projects/new")
        assert r.status_code == 200
        assert "form" in r.text.lower()

    def test_create_project(self, web_env):
        """POST /projects/new creates a new project."""
        r = web_env["client"].post("/projects/new", data={
            "name": "NewProject",
            "colmap_dir": str(web_env["colmap_dir"]),
            "trainer": "postshot",
            "lods": "5M,2M",
            "step_clean": "step_clean",
            "step_train": "step_train",
            "step_assemble": "step_assemble",
            "step_export": "step_export",
        }, follow_redirects=False)
        assert r.status_code == 303
        new_dir = web_env["projects_root"] / "NewProject"
        assert new_dir.exists()
        assert (new_dir / "state.json").exists()

    def test_create_missing_name(self, web_env):
        """POST /projects/new with no name returns error."""
        r = web_env["client"].post("/projects/new", data={
            "name": "",
            "colmap_dir": str(web_env["colmap_dir"]),
        })
        assert r.status_code == 200
        assert "required" in r.text.lower()


class TestProjectDetail:
    def test_detail_page(self, web_env):
        """GET /projects/{path}/detail returns 200 with project info."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        assert "TestProject" in r.text


class TestUpdateName:
    def test_update_name(self, web_env):
        """POST update-name changes the project name."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/update-name", data={"name": "Renamed"})
        assert r.status_code == 200
        # Reload and verify
        proj = Project(web_env["project"].root)
        assert proj.name == "Renamed"

    def test_empty_name(self, web_env):
        """POST update-name with empty name returns error."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/update-name", data={"name": ""})
        assert r.status_code == 200
        assert "error" in r.headers.get("hx-trigger", "").lower()


class TestUpdateTrainer:
    def test_update_trainer(self, web_env):
        """POST update-trainer changes the trainer."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/update-trainer", data={"trainer": "lichtfeld"})
        assert r.status_code == 200
        proj = Project(web_env["project"].root)
        assert proj.trainer == "lichtfeld"


class TestStepSettings:
    def test_update_step_settings(self, web_env):
        """POST update-step-settings saves settings."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/update-step-settings", data={
            "step_name": "clean",
            "kdtree_threshold": "0.005",
        })
        assert r.status_code == 200
        proj = Project(web_env["project"].root)
        assert proj.step_settings["clean"]["kdtree_threshold"] == 0.005

    def test_missing_step_name(self, web_env):
        """POST update-step-settings without step_name returns error."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/update-step-settings", data={
            "some_key": "value",
        })
        assert r.status_code == 200
        assert "error" in r.headers.get("hx-trigger", "").lower()


class TestToggleStep:
    def test_toggle_step(self, web_env):
        """POST toggle-step changes step enabled state."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/toggle-step", data={
            "step_name": "assemble",
            "enabled": "false",
        }, follow_redirects=False)
        # Should redirect back to detail
        assert r.status_code == 303
        proj = Project(web_env["project"].root)
        assert proj.is_step_enabled("assemble") is False


class TestToggleLod:
    def test_toggle_lod(self, web_env):
        """POST toggle-lod disables a LOD."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/toggle-lod", data={
            "index": "0",
            "enabled": "false",
        })
        assert r.status_code == 200
        proj = Project(web_env["project"].root)
        assert proj.lod_levels[0]["enabled"] is False


class TestClearStep:
    def test_clear_step(self, web_env):
        """POST clear-step clears step data and resets status."""
        proj = web_env["project"]
        # Record a step and create some output files
        proj.record_step("clean", "completed", summary={"test": True})
        clean_dir = proj.get_folder("02_colmap_clean")
        (clean_dir / "test.txt").write_text("data")

        path = str(proj.root)
        r = web_env["client"].post(f"/projects/{path}/clear-step/clean")
        assert r.status_code == 200

        proj2 = Project(proj.root)
        assert proj2.get_step_status("clean") is None
        assert not (clean_dir / "test.txt").exists()


class TestExportMode:
    def test_update_export_mode(self, web_env):
        """POST update-export-mode sets the mode."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/update-export-mode", data={
            "export_mode": "cdn",
        })
        assert r.status_code == 200
        proj = Project(web_env["project"].root)
        assert proj.export_mode == "cdn"

    def test_invalid_export_mode(self, web_env):
        """Invalid mode returns error."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/update-export-mode", data={
            "export_mode": "invalid",
        })
        assert "error" in r.headers.get("hx-trigger", "").lower()


class TestLodTrainSteps:
    def test_update_lod_train_steps(self, web_env):
        """POST update-lod-train-steps sets per-LOD steps."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/update-lod-train-steps", data={
            "index": "0",
            "train_steps": "50",
        })
        assert r.status_code == 200
        proj = Project(web_env["project"].root)
        assert proj.lod_levels[0]["train_steps"] == 50


# --- Settings routes ---


class TestSettingsPage:
    def test_settings_get(self, web_env):
        """GET /settings/ returns 200."""
        r = web_env["client"].get("/settings/")
        assert r.status_code == 200
        assert "Settings" in r.text

    def test_settings_post(self, web_env):
        """POST /settings/ saves config."""
        r = web_env["client"].post("/settings/", data={
            "paths__projects_root": str(web_env["projects_root"]),
            "tools__postshot": "",
            "tools__lichtfeld_studio": "",
            "tools__colmap": "",
            "tools__splat_transform": "",
            "tools__supersplat_url": "https://superspl.at/editor",
            "colmap_clean__outlier_threshold_fixed": "100.0",
            "colmap_clean__outlier_percentile": "0.99",
            "colmap_clean__outlier_multiplier": "2.5",
            "colmap_clean__kdtree_threshold": "0.001",
            "postshot__profile": "Splat3",
            "postshot__login": "",
            "postshot__password": "",
            "lichtfeld__strategy": "mcmc",
            "lichtfeld__iterations": "30000",
        })
        assert r.status_code == 200

    def test_check_deps(self, web_env):
        """GET /settings/check-deps returns JSON."""
        r = web_env["client"].get("/settings/check-deps")
        assert r.status_code == 200
        data = r.json()
        assert "numpy" in data


# --- Step execution routes ---


class TestStepRoutes:
    def test_run_step_returns_sse_panel(self, web_env):
        """POST /steps/{path}/run/{step} returns HTML with sse-connect."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/steps/{path}/run/clean")
        assert r.status_code == 200
        assert "sse-connect" in r.text
        assert "/progress" in r.text

    def test_run_all_returns_sse_panel(self, web_env):
        """POST /steps/{path}/run-all returns HTML with sse-connect."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/steps/{path}/run-all")
        assert r.status_code == 200
        assert "sse-connect" in r.text
        assert "/progress" in r.text

    def test_cancel_returns_html(self, web_env):
        """POST /steps/{path}/cancel returns cancelling message."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/steps/{path}/cancel")
        assert r.status_code == 200
        assert "Cancelling" in r.text

    def test_detail_resets_stale_running(self, web_env):
        """Detail page with no runner + 'running' status resets to failed."""
        proj = web_env["project"]
        proj.record_step("clean", "running")

        path = str(proj.root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200

        # Reload project — stale "running" should be reset to "failed"
        proj2 = Project(proj.root)
        assert proj2.get_step_status("clean") == "failed"

    def test_detail_shows_reconnect_for_active_runner(self, web_env):
        """Detail page with active runner shows SSE reconnect panel."""
        from unittest.mock import patch, MagicMock
        from splatpipe.web.runner import RunnerSnapshot

        proj = web_env["project"]
        proj.record_step("clean", "running")

        mock_runner = MagicMock()
        mock_runner.snapshot = RunnerSnapshot(
            status="running", current_step="clean",
            step_label="Running: Clean COLMAP (1/1)",
            progress=0.5, message="Working...",
            error=None, updated_at=0.0,
        )

        path = str(proj.root)
        with patch("splatpipe.web.routes.projects.get_runner", return_value=mock_runner):
            r = web_env["client"].get(f"/projects/{path}/detail")

        assert r.status_code == 200
        assert "sse-connect" in r.text
        assert "Reconnecting" in r.text
        # Run button should be hidden
        assert "Run Enabled" not in r.text


# --- Actions routes ---


class TestActions:
    def test_open_tool_unknown(self, web_env):
        """POST open-tool with unknown tool returns error toast."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/actions/{path}/open-tool", data={"tool": "unknown"})
        assert r.status_code == 200
        assert "error" in r.headers.get("hx-trigger", "").lower()

    def test_open_folder_nonexistent(self, web_env):
        """POST open-folder with nonexistent path returns error toast."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/actions/{path}/open-folder", data={
            "folder": r"C:\nonexistent\path\definitely",
        })
        assert r.status_code == 200
        assert "error" in r.headers.get("hx-trigger", "").lower()

    def test_open_folder_empty(self, web_env):
        """POST open-folder with empty path returns error."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/actions/{path}/open-folder", data={"folder": ""})
        assert r.status_code == 200
        assert "error" in r.headers.get("hx-trigger", "").lower()


# --- Review step routes ---


class TestApproveReview:
    def test_approve_review_no_plys(self, web_env):
        """Approve with empty review folder records 0 LODs."""
        proj = web_env["project"]
        path = str(proj.root)
        r = web_env["client"].post(f"/steps/{path}/approve-review")
        assert r.status_code == 200
        assert "approved" in r.text.lower()

        proj2 = Project(proj.root)
        assert proj2.get_step_status("review") == "completed"
        summary = proj2.get_step_summary("review")
        assert summary["lod_count"] == 0

    def test_approve_review_with_plys(self, web_env):
        """Approve with PLY files records correct LOD count and vertex total."""
        proj = web_env["project"]
        review_dir = proj.get_folder("04_review")
        # Create a minimal PLY with vertex count in header
        ply_header = b"ply\nformat binary_little_endian 1.0\nelement vertex 5000000\nend_header\n"
        (review_dir / "lod0_reviewed.ply").write_bytes(ply_header)
        (review_dir / "lod1_reviewed.ply").write_bytes(ply_header)

        path = str(proj.root)
        r = web_env["client"].post(f"/steps/{path}/approve-review")
        assert r.status_code == 200
        assert "2 LODs" in r.text

        proj2 = Project(proj.root)
        summary = proj2.get_step_summary("review")
        assert summary["lod_count"] == 2
        assert summary["total_vertices"] == 10_000_000

    def test_detail_shows_review_step(self, web_env):
        """Project detail page includes the Review Splats step."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        assert "Review Splats" in r.text

    def test_detail_shows_approve_button_when_train_complete(self, web_env):
        """After train completes, the review card shows Approve button."""
        proj = web_env["project"]
        proj.record_step("train", "completed", summary={"lod_count": 2})
        # Create review PLYs
        review_dir = proj.get_folder("04_review")
        ply_header = b"ply\nformat binary_little_endian 1.0\nelement vertex 1000000\nend_header\n"
        (review_dir / "lod0_reviewed.ply").write_bytes(ply_header)

        path = str(proj.root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        assert "Approve &amp; Continue" in r.text or "Approve" in r.text
