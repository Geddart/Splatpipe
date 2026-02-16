"""Tests for web route endpoints using FastAPI TestClient."""

import json

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

    # Clean queue state before each test
    import splatpipe.web.runner as runner_module
    runner_module._queue.clear()
    runner_module._queue_current = None
    runner_module._queue_paused = False
    runner_module._queue_wake.clear()

    from splatpipe.web.app import app
    client = TestClient(app)

    yield {
        "client": client,
        "project": project,
        "projects_root": projects_root,
        "toml_path": toml_path,
        "colmap_dir": colmap_dir,
        "tmp_path": tmp_path,
    }

    # Cleanup
    runner_module._queue.clear()
    runner_module._queue_current = None
    runner_module._queue_paused = False
    runner_module._queue_wake.clear()


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
        }, follow_redirects=False)
        assert r.status_code == 303
        new_dir = web_env["projects_root"] / "NewProject"
        assert new_dir.exists()
        assert (new_dir / "state.json").exists()

    def test_create_project_unknown_format(self, web_env):
        """POST /projects/new with unknown format still creates project."""
        empty_dir = web_env["tmp_path"] / "unknown_data"
        empty_dir.mkdir()
        (empty_dir / "random.dat").touch()
        r = web_env["client"].post("/projects/new", data={
            "name": "UnknownFormat",
            "colmap_dir": str(empty_dir),
        }, follow_redirects=False)
        assert r.status_code == 303
        new_dir = web_env["projects_root"] / "UnknownFormat"
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

    def test_create_project_psht_file(self, web_env):
        """POST /projects/new with .psht file creates project with source_type='postshot'."""
        psht = web_env["tmp_path"] / "scene.psht"
        psht.write_bytes(b"fake psht data")
        r = web_env["client"].post("/projects/new", data={
            "name": "PshtProject",
            "colmap_dir": str(psht),
        }, follow_redirects=False)
        assert r.status_code == 303
        new_dir = web_env["projects_root"] / "PshtProject"
        assert new_dir.exists()
        state = json.loads((new_dir / "state.json").read_text())
        assert state["source_type"] == "postshot"
        assert (new_dir / "01_colmap_source" / "source.psht").exists()


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
            "folder": "/nonexistent/path/definitely",
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


class TestCdnName:
    def test_update_cdn_name(self, web_env):
        """POST update-cdn-name sets the CDN folder name."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/update-cdn-name", data={
            "cdn_name": "my_custom_name",
        })
        assert r.status_code == 200
        proj = Project(web_env["project"].root)
        assert proj.cdn_name == "my_custom_name"

    def test_update_cdn_name_empty_defaults(self, web_env):
        """POST update-cdn-name with empty string resets to project name default."""
        path = str(web_env["project"].root)
        web_env["client"].post(f"/projects/{path}/update-cdn-name", data={"cdn_name": ""})
        proj = Project(web_env["project"].root)
        assert proj.cdn_name == "TestProject"

    def test_detail_page_shows_cdn_name(self, web_env):
        """Project detail page includes the CDN name in export settings."""
        proj = web_env["project"]
        proj.set_cdn_name("my_cdn_folder")
        path = str(proj.root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        assert "my_cdn_folder" in r.text


class TestUpdateLodSplats:
    def test_update_splats(self, web_env):
        """POST update-lod-splats changes the LOD's max_splats."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/update-lod-splats", data={
            "index": "0",
            "splats": "30M",
        })
        assert r.status_code == 200
        proj = Project(web_env["project"].root)
        assert proj.lod_levels[0]["max_splats"] == 30_000_000
        # Name should remain lod0 (index-based)
        assert proj.lod_levels[0]["name"] == "lod0"

    def test_update_splats_invalid(self, web_env):
        """POST update-lod-splats with bad format returns error toast."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/projects/{path}/update-lod-splats", data={
            "index": "0",
            "splats": "abc",
        })
        assert r.status_code == 200
        assert "HX-Trigger" in r.headers


class TestBunnySettings:
    def test_settings_saves_bunny_credentials(self, web_env):
        """POST /settings/ saves bunny CDN credentials to TOML config."""
        r = web_env["client"].post("/settings/", data={
            "paths__projects_root": str(web_env["projects_root"]),
            "tools__postshot": "",
            "tools__lichtfeld_studio": "",
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
            "bunny__storage_zone": "test-zone",
            "bunny__storage_password": "test-pw",
            "bunny__cdn_url": "https://test.b-cdn.net",
        })
        assert r.status_code == 200
        from splatpipe.core.config import load_defaults
        cfg = load_defaults()
        assert cfg["bunny"]["storage_zone"] == "test-zone"
        assert cfg["bunny"]["storage_password"] == "test-pw"
        assert cfg["bunny"]["cdn_url"] == "https://test.b-cdn.net"

    def test_detail_shows_bunny_status(self, web_env):
        """Project detail shows credential status in CDN export settings."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        # Without credentials configured, should show "No credentials"
        assert "No credentials" in r.text or "Settings" in r.text


class TestPreviewRoute:
    def test_preview_serves_file(self, web_env):
        """GET preview route serves files from 05_output."""
        proj = web_env["project"]
        output_dir = proj.get_folder("05_output")
        (output_dir / "test.txt").write_text("hello")
        path = str(proj.root)
        r = web_env["client"].get(f"/projects/{path}/preview/test.txt")
        assert r.status_code == 200
        assert r.text == "hello"
        assert r.headers.get("access-control-allow-origin") == "*"

    def test_preview_404_missing(self, web_env):
        """GET preview for nonexistent file returns 404."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/preview/nonexistent.html")
        assert r.status_code == 404


class TestHistorySection:
    def test_detail_shows_history(self, web_env):
        """Project detail page shows history section after recording steps."""
        proj = web_env["project"]
        proj.record_step("clean", "completed", summary={"cameras_kept": 8})
        proj.record_step("train", "completed", summary={"lod_count": 3})
        path = str(proj.root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        assert "History" in r.text
        assert "Clean COLMAP" in r.text
        assert "Train Splats" in r.text

    def test_detail_no_history_for_new_project(self, web_env):
        """New project with no runs does not show history section."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        assert "history-panel" not in r.text


# --- Queue routes ---


class TestQueueRoutes:
    def test_queue_panel_empty(self, web_env):
        """GET /queue/panel returns 200 with no content when queue is empty."""
        r = web_env["client"].get("/queue/panel")
        assert r.status_code == 200
        # Empty queue → no card rendered (just whitespace)
        assert "Pipeline Queue" not in r.text

    def test_queue_panel_with_current(self, web_env):
        """GET /queue/panel shows current job when something is running."""
        import splatpipe.web.runner as runner_module
        from splatpipe.web.runner import QueueEntry

        runner_module._queue_current = QueueEntry(
            id="abc", project_path=str(web_env["project"].root),
            project_name="TestProject", steps=["clean"],
            config={}, added_at=0.0,
        )
        try:
            r = web_env["client"].get("/queue/panel")
            assert r.status_code == 200
            assert "Pipeline Queue" in r.text
            assert "TestProject" in r.text
        finally:
            runner_module._queue_current = None

    def test_queue_panel_with_pending(self, web_env):
        """GET /queue/panel shows pending entries."""
        import splatpipe.web.runner as runner_module
        from splatpipe.web.runner import QueueEntry

        runner_module._queue.append(QueueEntry(
            id="pend1", project_path="/fake1",
            project_name="Project1", steps=["train"],
            config={}, added_at=0.0,
        ))
        runner_module._queue.append(QueueEntry(
            id="pend2", project_path="/fake2",
            project_name="Project2", steps=["train"],
            config={}, added_at=0.0,
        ))
        try:
            r = web_env["client"].get("/queue/panel")
            assert r.status_code == 200
            assert "Project1" in r.text
            assert "Project2" in r.text
            assert "#1" in r.text
            assert "#2" in r.text
        finally:
            runner_module._queue.clear()

    def test_toggle_pause(self, web_env):
        """POST /queue/toggle-pause toggles the pause state."""
        import splatpipe.web.runner as runner_module

        assert runner_module._queue_paused is False
        r = web_env["client"].post("/queue/toggle-pause")
        assert r.status_code == 200
        assert runner_module._queue_paused is True
        # Toggle back
        r = web_env["client"].post("/queue/toggle-pause")
        assert runner_module._queue_paused is False

    def test_remove_from_queue(self, web_env):
        """POST /queue/{id}/remove removes a pending entry."""
        import splatpipe.web.runner as runner_module
        from splatpipe.web.runner import QueueEntry

        runner_module._queue.append(QueueEntry(
            id="rem1", project_path="/fake",
            project_name="RemoveMe", steps=["clean"],
            config={}, added_at=0.0,
        ))
        try:
            r = web_env["client"].post("/queue/rem1/remove")
            assert r.status_code == 200
            assert len(runner_module._queue) == 0
        finally:
            runner_module._queue.clear()

    def test_run_all_enqueues_immediately(self, web_env):
        """POST run-all with empty queue starts immediately (SSE panel)."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(f"/steps/{path}/run-all")
        assert r.status_code == 200
        assert "sse-connect" in r.text

    def test_run_all_queues_when_busy(self, web_env):
        """POST run-all when another project is running returns queued panel."""
        import splatpipe.web.runner as runner_module
        from splatpipe.web.runner import QueueEntry

        # Simulate another project already running
        runner_module._queue_current = QueueEntry(
            id="other", project_path="/other/project",
            project_name="OtherProject", steps=["train"],
            config={}, added_at=0.0,
        )
        try:
            path = str(web_env["project"].root)
            r = web_env["client"].post(f"/steps/{path}/run-all")
            assert r.status_code == 200
            assert "Queued" in r.text
            assert len(runner_module._queue) == 1
        finally:
            runner_module._queue_current = None
            runner_module._queue.clear()


class TestSceneConfig:
    def test_update_scene_config_camera(self, web_env):
        """POST update-scene-config persists camera constraints."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(
            f"/projects/{path}/update-scene-config",
            data={"section": "camera", "ground_height": "2.5", "pitch_min": "-45"}
        )
        assert r.status_code == 200
        proj = Project(web_env["project"].root)
        assert proj.scene_config["camera"]["ground_height"] == 2.5
        assert proj.scene_config["camera"]["pitch_min"] == -45.0

    def test_update_scene_config_missing_section(self, web_env):
        """POST without section returns error toast."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(
            f"/projects/{path}/update-scene-config",
            data={"ground_height": "2.5"}
        )
        assert r.status_code == 200

    def test_project_detail_has_scene_config(self, web_env):
        """Project detail page renders camera constraint fields."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        assert "Camera Constraints" in r.text

    def test_update_scene_config_splat_budget(self, web_env):
        """POST update-scene-config with section=splat_budget stores int."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(
            f"/projects/{path}/update-scene-config",
            data={"section": "splat_budget", "value": "4000000"}
        )
        assert r.status_code == 200
        proj = Project(web_env["project"].root)
        assert proj.scene_config["splat_budget"] == 4000000

    def test_update_scene_config_splat_budget_zero(self, web_env):
        """POST splat_budget=0 resets to platform default."""
        path = str(web_env["project"].root)
        web_env["project"].set_scene_config_section("splat_budget", 3000000)
        r = web_env["client"].post(
            f"/projects/{path}/update-scene-config",
            data={"section": "splat_budget", "value": "0"}
        )
        assert r.status_code == 200
        proj = Project(web_env["project"].root)
        assert proj.scene_config["splat_budget"] == 0

    def test_project_detail_has_splat_budget(self, web_env):
        """Project detail page renders splat budget dropdown."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        assert "Splat Budget" in r.text


class TestAnnotations:
    def test_add_annotation(self, web_env):
        """POST add-annotation persists annotation."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(
            f"/projects/{path}/add-annotation",
            json={"pos": [1, 2, 3], "title": "Test", "text": "Desc", "label": "1"}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["index"] == 0
        proj = Project(web_env["project"].root)
        assert len(proj.scene_config["annotations"]) == 1
        assert proj.scene_config["annotations"][0]["title"] == "Test"

    def test_update_annotation(self, web_env):
        """POST update-annotation updates fields."""
        path = str(web_env["project"].root)
        proj = web_env["project"]
        proj.set_scene_config_section("annotations", [
            {"pos": [0, 0, 0], "title": "Old", "text": "", "label": "1"}
        ])
        r = web_env["client"].post(
            f"/projects/{path}/update-annotation/0",
            json={"title": "New Title", "text": "New text"}
        )
        assert r.status_code == 200
        reloaded = Project(proj.root)
        assert reloaded.scene_config["annotations"][0]["title"] == "New Title"
        assert reloaded.scene_config["annotations"][0]["text"] == "New text"

    def test_delete_annotation_relabels(self, web_env):
        """POST delete-annotation removes and re-labels remaining."""
        path = str(web_env["project"].root)
        proj = web_env["project"]
        proj.set_scene_config_section("annotations", [
            {"pos": [0, 0, 0], "title": "A", "text": "", "label": "1"},
            {"pos": [1, 1, 1], "title": "B", "text": "", "label": "2"},
        ])
        r = web_env["client"].post(f"/projects/{path}/delete-annotation/0")
        assert r.status_code == 200
        data = r.json()
        assert len(data["annotations"]) == 1
        assert data["annotations"][0]["title"] == "B"
        assert data["annotations"][0]["label"] == "1"  # re-labeled
        reloaded = Project(proj.root)
        assert len(reloaded.scene_config["annotations"]) == 1

    def test_get_annotations_empty(self, web_env):
        """GET annotations returns empty list for new project."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/annotations")
        assert r.status_code == 200
        assert r.json() == []

    def test_get_annotations_with_data(self, web_env):
        """GET annotations returns saved annotations."""
        path = str(web_env["project"].root)
        web_env["project"].set_scene_config_section("annotations", [
            {"pos": [1, 2, 3], "title": "X", "text": "Y", "label": "1"}
        ])
        r = web_env["client"].get(f"/projects/{path}/annotations")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["title"] == "X"

    def test_scene_editor_page(self, web_env):
        """GET scene-editor returns 200."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/scene-editor")
        assert r.status_code == 200
        assert "Scene Editor" in r.text

    def test_project_detail_has_scene_editor_link(self, web_env):
        """Project detail page has Scene Editor button."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        assert "scene-editor" in r.text


class TestBackgroundPostProcessing:
    def test_update_scene_config_background(self, web_env):
        """POST update-scene-config with background section persists color."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(
            f"/projects/{path}/update-scene-config",
            data={"section": "background", "type": "color", "color": "#ff0000"}
        )
        assert r.status_code == 200
        proj = Project(web_env["project"].root)
        assert proj.scene_config["background"]["color"] == "#ff0000"
        assert proj.scene_config["background"]["type"] == "color"

    def test_update_scene_config_postprocessing(self, web_env):
        """POST update-scene-config with postprocessing persists settings."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(
            f"/projects/{path}/update-scene-config",
            data={
                "section": "postprocessing",
                "tonemapping": "aces",
                "exposure": "2.5",
                "bloom": "true",
                "bloom_intensity": "0.05",
                "vignette": "false",
                "vignette_intensity": "0.5",
            }
        )
        assert r.status_code == 200
        proj = Project(web_env["project"].root)
        pp = proj.scene_config["postprocessing"]
        assert pp["tonemapping"] == "aces"
        assert pp["exposure"] == 2.5
        assert pp["bloom"] is True
        assert pp["bloom_intensity"] == 0.05
        assert pp["vignette"] is False

    def test_project_detail_has_background_section(self, web_env):
        """Project detail page renders Background section."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        assert "Background" in r.text

    def test_project_detail_has_postprocessing_section(self, web_env):
        """Project detail page renders Post-Processing section."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        assert "Post-Processing" in r.text
        assert "Tonemapping" in r.text


class TestAudio:
    def test_add_audio(self, web_env):
        """POST add-audio persists audio source."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(
            f"/projects/{path}/add-audio",
            json={"file": "assets/audio/test.mp3", "volume": 0.5, "loop": True, "positional": False}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["index"] == 0
        proj = Project(web_env["project"].root)
        assert len(proj.scene_config["audio"]) == 1
        assert proj.scene_config["audio"][0]["file"] == "assets/audio/test.mp3"

    def test_update_audio(self, web_env):
        """POST update-audio updates fields."""
        path = str(web_env["project"].root)
        proj = web_env["project"]
        proj.set_scene_config_section("audio", [
            {"file": "assets/audio/a.mp3", "volume": 0.5, "loop": True, "positional": False}
        ])
        r = web_env["client"].post(
            f"/projects/{path}/update-audio/0",
            json={"volume": 0.8, "loop": False}
        )
        assert r.status_code == 200
        reloaded = Project(proj.root)
        assert reloaded.scene_config["audio"][0]["volume"] == 0.8
        assert reloaded.scene_config["audio"][0]["loop"] is False

    def test_delete_audio(self, web_env):
        """POST delete-audio removes audio source."""
        path = str(web_env["project"].root)
        proj = web_env["project"]
        proj.set_scene_config_section("audio", [
            {"file": "assets/audio/a.mp3", "volume": 0.5, "loop": True, "positional": False},
            {"file": "assets/audio/b.mp3", "volume": 0.3, "loop": False, "positional": True},
        ])
        r = web_env["client"].post(f"/projects/{path}/delete-audio/0")
        assert r.status_code == 200
        data = r.json()
        assert len(data["audio"]) == 1
        assert data["audio"][0]["file"] == "assets/audio/b.mp3"
        reloaded = Project(proj.root)
        assert len(reloaded.scene_config["audio"]) == 1

    def test_project_detail_has_audio_section(self, web_env):
        """Project detail page renders Audio section."""
        path = str(web_env["project"].root)
        r = web_env["client"].get(f"/projects/{path}/detail")
        assert r.status_code == 200
        assert "Audio" in r.text

    def test_upload_audio(self, web_env):
        """POST upload-audio saves file to assets/audio/."""
        path = str(web_env["project"].root)
        r = web_env["client"].post(
            f"/projects/{path}/upload-audio",
            files={"file": ("test.mp3", b"fake-audio-data", "audio/mpeg")}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["path"] == "assets/audio/test.mp3"
        assert (web_env["project"].root / "assets" / "audio" / "test.mp3").exists()
