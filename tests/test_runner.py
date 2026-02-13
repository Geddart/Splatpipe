"""Tests for the background PipelineRunner."""

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from splatpipe.core.events import ProgressEvent
from splatpipe.core.project import Project
from splatpipe.trainers.base import TrainResult
from splatpipe.web.runner import (
    PipelineRunner,
    RunnerSnapshot,
    start_run,
    get_runner,
    cancel_run,
    _runners,
    _runners_lock,
)


@pytest.fixture
def runner_project(tmp_path):
    """Create a minimal project for runner tests."""
    proj_dir = tmp_path / "TestRunnerProject"
    colmap_dir = tmp_path / "colmap"
    colmap_dir.mkdir()
    (colmap_dir / "cameras.txt").write_text("# 3 cameras\n")
    (colmap_dir / "images.txt").write_text("# 5 images\n")
    (colmap_dir / "points3D.txt").write_text("# 50 points\n")

    proj = Project.create(
        proj_dir, "TestRunnerProject",
        colmap_source=str(colmap_dir),
        lod_levels=[
            {"name": "lod0_5000k", "max_splats": 5_000_000},
            {"name": "lod1_2000k", "max_splats": 2_000_000},
        ],
    )
    return proj


@pytest.fixture(autouse=True)
def clean_runners():
    """Clear the global runners dict before each test."""
    with _runners_lock:
        _runners.clear()
    yield
    with _runners_lock:
        # Cancel any leftover runners
        for r in _runners.values():
            r.cancel()
        _runners.clear()


def _make_config():
    """Minimal config for tests."""
    return {
        "postshot": {
            "profile": "Splat3",
            "downsample": True,
            "max_image_size": 3840,
            "anti_aliasing": False,
            "create_sky_model": False,
            "train_steps_limit": 0,
        },
        "colmap_clean": {},
    }


class TestRunnerSnapshot:
    def test_snapshot_is_immutable(self):
        snap = RunnerSnapshot(
            status="running", current_step="clean",
            step_label="Running: Clean COLMAP (1/1)",
            progress=0.5, message="Working...",
            error=None, updated_at=time.monotonic(),
        )
        with pytest.raises(AttributeError):
            snap.status = "completed"

    def test_snapshot_fields(self):
        snap = RunnerSnapshot(
            status="failed", current_step="train",
            step_label="Running: Train Splats (2/3)",
            progress=0.3, message="LOD lod0",
            error="boom", updated_at=1.0,
        )
        assert snap.status == "failed"
        assert snap.current_step == "train"
        assert snap.error == "boom"


class TestPipelineRunnerClean:
    def test_runner_completes_clean_step(self, runner_project):
        """Runner completes a single clean step via mocked ColmapCleanStep."""
        config = _make_config()
        runner = PipelineRunner(str(runner_project.root), ["clean"], config)

        with patch("splatpipe.web.runner.ColmapCleanStep") as mock_cls:
            mock_step = MagicMock()
            mock_step.execute.return_value = {"summary": {"cameras_kept": 3}}
            mock_cls.return_value = mock_step

            runner.start()
            runner._thread.join(timeout=5)

        snap = runner.snapshot
        assert snap.status == "completed"
        assert snap.progress == 1.0

    def test_runner_handles_clean_failure(self, runner_project):
        """Runner catches exceptions and sets failed status."""
        config = _make_config()
        runner = PipelineRunner(str(runner_project.root), ["clean"], config)

        with patch("splatpipe.web.runner.ColmapCleanStep") as mock_cls:
            mock_step = MagicMock()
            mock_step.execute.side_effect = FileNotFoundError("cameras.txt missing")
            mock_cls.return_value = mock_step

            runner.start()
            runner._thread.join(timeout=5)

        snap = runner.snapshot
        assert snap.status == "failed"
        assert "cameras.txt missing" in snap.error


class TestPipelineRunnerTrain:
    @staticmethod
    def _mock_train_lod(source_dir, output_dir, lod_name, max_splats, **kwargs):
        """Generator that yields a few progress events then returns TrainResult."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        for i in range(3):
            yield ProgressEvent(
                step="train", progress=i / 3,
                message=f"Step {i+1}/3", sub_progress=(i + 1) / 3,
            )
        return TrainResult(
            lod_name=lod_name, max_splats=max_splats,
            success=True, command=["mock"],
            returncode=0, stdout="", stderr="",
            duration_s=1.0, output_dir=str(output_dir), output_ply="",
        )

    def test_runner_completes_train_step(self, runner_project):
        """Runner trains all LODs via mocked trainer."""
        config = _make_config()
        runner = PipelineRunner(str(runner_project.root), ["train"], config)

        with patch("splatpipe.web.runner.get_trainer") as mock_get:
            mock_trainer = MagicMock()
            mock_trainer.train_lod.side_effect = self._mock_train_lod
            mock_get.return_value = mock_trainer

            runner.start()
            runner._thread.join(timeout=10)

        snap = runner.snapshot
        assert snap.status == "completed"
        assert snap.progress == 1.0
        # Verify state.json was updated
        proj = Project(runner_project.root)
        assert proj.get_step_status("train") == "completed"
        summary = proj.get_step_summary("train")
        assert summary["lod_count"] == 2

    def test_runner_multi_lod_writes_review_plys(self, runner_project):
        """Verify PLY copy to review folder during training."""
        config = _make_config()

        def mock_train(source_dir, output_dir, lod_name, max_splats, **kwargs):
            # Create a fake PLY in the training dir
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            ply_path = Path(output_dir) / f"{lod_name}.ply"
            ply_path.write_text("fake ply data")
            yield ProgressEvent(step="train", progress=0.5, message="Training...", sub_progress=0.5)
            return TrainResult(
                lod_name=lod_name, max_splats=max_splats,
                success=True, command=["mock"],
                returncode=0, stdout="", stderr="",
                duration_s=1.0, output_dir=str(output_dir),
                output_ply=str(ply_path),
            )

        runner = PipelineRunner(str(runner_project.root), ["train"], config)

        with patch("splatpipe.web.runner.get_trainer") as mock_get:
            mock_trainer = MagicMock()
            mock_trainer.train_lod.side_effect = mock_train
            mock_get.return_value = mock_trainer

            runner.start()
            runner._thread.join(timeout=10)

        assert runner.snapshot.status == "completed"
        review_dir = runner_project.get_folder("04_review")
        assert (review_dir / "lod0_reviewed.ply").exists()
        assert (review_dir / "lod1_reviewed.ply").exists()


class TestPipelineRunnerCancel:
    def test_cancel_stops_execution(self, runner_project):
        """Cancel during training stops the runner."""
        config = _make_config()

        def slow_train(source_dir, output_dir, lod_name, max_splats, **kwargs):
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            for i in range(100):
                yield ProgressEvent(
                    step="train", progress=i / 100,
                    message=f"Step {i}", sub_progress=i / 100,
                )
                time.sleep(0.05)
            return TrainResult(
                lod_name=lod_name, max_splats=max_splats,
                success=True, command=[], returncode=0,
                stdout="", stderr="", duration_s=1.0,
                output_dir=str(output_dir), output_ply="",
            )

        runner = PipelineRunner(str(runner_project.root), ["train"], config)

        with patch("splatpipe.web.runner.get_trainer") as mock_get:
            mock_trainer = MagicMock()
            mock_trainer.train_lod.side_effect = slow_train
            mock_get.return_value = mock_trainer

            runner.start()
            time.sleep(0.3)
            runner.cancel()
            runner._thread.join(timeout=5)

        snap = runner.snapshot
        assert snap.status == "cancelled"


class TestModuleLevelAPI:
    def test_get_runner_none_when_empty(self):
        assert get_runner("nonexistent/path") is None

    def test_start_run_creates_runner(self, runner_project):
        config = _make_config()
        with patch("splatpipe.web.runner.ColmapCleanStep") as mock_cls:
            mock_step = MagicMock()
            mock_step.execute.return_value = {"summary": {}}
            mock_cls.return_value = mock_step

            runner = start_run(str(runner_project.root), ["clean"], config)
            assert get_runner(str(runner_project.root)) is runner
            runner._thread.join(timeout=5)

    def test_start_run_replaces_old(self, runner_project):
        """Second start_run cancels first runner."""
        config = _make_config()

        def slow_clean_execute():
            time.sleep(5)
            return {"summary": {}}

        with patch("splatpipe.web.runner.ColmapCleanStep") as mock_cls:
            mock_step = MagicMock()
            mock_step.execute.side_effect = slow_clean_execute
            mock_cls.return_value = mock_step

            runner1 = start_run(str(runner_project.root), ["clean"], config)
            time.sleep(0.1)

            # Second run should cancel the first
            runner2 = start_run(str(runner_project.root), ["clean"], config)

            assert get_runner(str(runner_project.root)) is runner2
            # First runner should have been cancelled
            assert runner1._cancel_event.is_set()
            runner2._thread.join(timeout=5)

    def test_cancel_run(self, runner_project):
        config = _make_config()

        def slow_clean_execute():
            time.sleep(5)
            return {"summary": {}}

        with patch("splatpipe.web.runner.ColmapCleanStep") as mock_cls:
            mock_step = MagicMock()
            mock_step.execute.side_effect = slow_clean_execute
            mock_cls.return_value = mock_step

            start_run(str(runner_project.root), ["clean"], config)
            assert cancel_run(str(runner_project.root)) is True
            assert cancel_run("nonexistent") is False


class TestRunnerSnapshotThreadSafety:
    def test_concurrent_reads_dont_deadlock(self, runner_project):
        """Multiple threads reading snapshot concurrently should not deadlock."""
        config = _make_config()

        def slow_clean_execute():
            time.sleep(1)
            return {"summary": {}}

        with patch("splatpipe.web.runner.ColmapCleanStep") as mock_cls:
            mock_step = MagicMock()
            mock_step.execute.side_effect = slow_clean_execute
            mock_cls.return_value = mock_step

            runner = start_run(str(runner_project.root), ["clean"], config)

            results = []
            errors = []

            def read_snapshot():
                try:
                    for _ in range(20):
                        snap = runner.snapshot
                        results.append(snap.status)
                        time.sleep(0.01)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=read_snapshot) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

            assert not errors, f"Errors during concurrent reads: {errors}"
            assert len(results) == 100  # 5 threads * 20 reads
            runner._thread.join(timeout=5)


class TestPipelineRunnerReview:
    def test_review_skips_when_already_approved(self, runner_project):
        """If review is already completed, runner skips through immediately."""
        config = _make_config()
        runner_project.record_step("review", "completed", summary={"lod_count": 2})

        runner = PipelineRunner(str(runner_project.root), ["review"], config)
        runner.start()
        runner._thread.join(timeout=5)

        snap = runner.snapshot
        assert snap.status == "completed"
        assert snap.progress == 1.0

    def test_review_waits_for_approval(self, runner_project):
        """Runner waits at review step until status changes to completed."""
        config = _make_config()
        runner = PipelineRunner(str(runner_project.root), ["review"], config)
        runner.start()

        # Let it enter the waiting loop
        time.sleep(1)
        snap = runner.snapshot
        assert snap.status == "running"
        assert "manual review" in snap.message.lower()

        # Simulate user clicking Approve
        runner_project.record_step("review", "completed", summary={"lod_count": 1})

        runner._thread.join(timeout=10)
        snap = runner.snapshot
        assert snap.status == "completed"
        assert snap.progress == 1.0

    def test_review_cancellable_while_waiting(self, runner_project):
        """Cancelling while waiting for review stops the runner."""
        config = _make_config()
        runner = PipelineRunner(str(runner_project.root), ["review"], config)
        runner.start()

        time.sleep(0.5)
        runner.cancel()
        runner._thread.join(timeout=5)

        snap = runner.snapshot
        assert snap.status == "cancelled"


class TestRunnerMultiStep:
    def test_runner_completes_clean_and_train(self, runner_project):
        """Runner executes clean then train in sequence."""
        config = _make_config()

        def mock_train(source_dir, output_dir, lod_name, max_splats, **kwargs):
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            yield ProgressEvent(step="train", progress=0.5, message="Training...", sub_progress=0.5)
            return TrainResult(
                lod_name=lod_name, max_splats=max_splats,
                success=True, command=["mock"],
                returncode=0, stdout="", stderr="",
                duration_s=1.0, output_dir=str(output_dir), output_ply="",
            )

        with patch("splatpipe.web.runner.ColmapCleanStep") as mock_clean_cls, \
             patch("splatpipe.web.runner.get_trainer") as mock_get:
            mock_step = MagicMock()
            mock_step.execute.return_value = {"summary": {"cameras_kept": 3}}
            mock_clean_cls.return_value = mock_step

            mock_trainer = MagicMock()
            mock_trainer.train_lod.side_effect = mock_train
            mock_get.return_value = mock_trainer

            runner = PipelineRunner(str(runner_project.root), ["clean", "train"], config)
            runner.start()
            runner._thread.join(timeout=10)

        snap = runner.snapshot
        assert snap.status == "completed"
        assert snap.progress == 1.0

        proj = Project(runner_project.root)
        assert proj.get_step_status("clean") == "completed"
        assert proj.get_step_status("train") == "completed"
