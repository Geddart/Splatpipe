"""Tests for trainer abstraction, Postshot, and LichtFeld trainers."""

from unittest.mock import patch, MagicMock

import pytest

from splatpipe.trainers.postshot import PostshotTrainer
from splatpipe.trainers.lichtfeld import LichtfeldTrainer
from splatpipe.trainers.registry import get_trainer, list_trainers


class TestRegistry:
    def test_list_trainers(self):
        trainers = list_trainers()
        assert "postshot" in trainers
        assert "lichtfeld" in trainers

    def test_get_postshot(self):
        config = {"tools": {}}
        trainer = get_trainer("postshot", config)
        assert isinstance(trainer, PostshotTrainer)
        assert trainer.name == "postshot"

    def test_get_lichtfeld(self):
        config = {"tools": {}}
        trainer = get_trainer("lichtfeld", config)
        assert isinstance(trainer, LichtfeldTrainer)
        assert trainer.name == "lichtfeld"

    def test_unknown_trainer(self):
        with pytest.raises(KeyError, match="Unknown trainer"):
            get_trainer("nonexistent", {})


class TestPostshotTrainer:
    def test_validate_missing(self):
        config = {"tools": {}}
        trainer = PostshotTrainer(config)
        ok, msg = trainer.validate_environment()
        assert ok is False
        assert "not configured" in msg

    def test_validate_nonexistent(self):
        config = {"tools": {"postshot_cli": r"C:\nonexistent\tool.exe"}}
        trainer = PostshotTrainer(config)
        ok, msg = trainer.validate_environment()
        assert ok is False
        assert "not found" in msg.lower()

    def test_validate_exists(self, tmp_path):
        fake_exe = tmp_path / "postshot-cli.exe"
        fake_exe.write_text("")
        config = {"tools": {"postshot_cli": str(fake_exe)}}
        trainer = PostshotTrainer(config)
        ok, msg = trainer.validate_environment()
        assert ok is True

    def test_parse_progress_step(self):
        trainer = PostshotTrainer({})
        assert trainer.parse_progress("Step 100/5000") == pytest.approx(0.02)
        assert trainer.parse_progress("step 2500/5000") == pytest.approx(0.5)
        assert trainer.parse_progress("Step 5000/5000") == pytest.approx(1.0)
        assert trainer.parse_progress("Some other line") is None

    def test_compute_training_steps(self):
        trainer = PostshotTrainer({})
        # 500 images -> max(50, round(500*52/1000)) = max(50, 26) = 50
        assert trainer.compute_training_steps(500) == 50
        # 2000 images -> max(50, round(2000*52/1000)) = max(50, 104) = 104
        assert trainer.compute_training_steps(2000) == 104

    def test_train_lod_with_mock(self, tmp_path):
        """Train a LOD with mocked Popen."""
        fake_exe = tmp_path / "postshot-cli.exe"
        fake_exe.write_text("")
        config = {"tools": {"postshot_cli": str(fake_exe)}}
        trainer = PostshotTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([
            "Step 1/100\n",
            "Step 50/100\n",
            "Step 100/100\n",
        ])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc):
            gen = trainer.train_lod(
                tmp_path / "colmap", tmp_path / "output",
                "lod0_3000k", 3_000_000,
            )

            events = []
            result = None
            try:
                while True:
                    event = next(gen)
                    events.append(event)
            except StopIteration as e:
                result = e.value

        assert result is not None
        assert result.lod_name == "lod0_3000k"
        assert result.max_splats == 3_000_000
        assert result.success is True
        # Should have initial event + 3 progress events
        assert len(events) >= 3
        assert events[-1].sub_progress == pytest.approx(1.0)

    def test_train_lod_failure(self, tmp_path):
        """Non-zero exit code produces failed TrainResult."""
        fake_exe = tmp_path / "postshot-cli.exe"
        fake_exe.write_text("")
        config = {"tools": {"postshot_cli": str(fake_exe)}}
        trainer = PostshotTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = "CUDA out of memory"
        mock_proc.returncode = 1
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc):
            gen = trainer.train_lod(
                tmp_path / "colmap", tmp_path / "output",
                "lod0_3000k", 3_000_000,
            )
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result.success is False
        assert result.returncode == 1
        assert "CUDA out of memory" in result.stderr

    def test_ksplats_conversion(self, tmp_path):
        """Verify CLI gets kSplats not raw splat count."""
        fake_exe = tmp_path / "postshot-cli.exe"
        fake_exe.write_text("")
        config = {"tools": {"postshot_cli": str(fake_exe)}}
        trainer = PostshotTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            gen = trainer.train_lod(
                tmp_path / "colmap", tmp_path / "output",
                "lod0_3000k", 3_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        # 3_000_000 should become "3000" in the command
        idx = cmd.index("--max-num-splats")
        assert cmd[idx + 1] == "3000"


class TestLichtfeldTrainer:
    def test_validate_missing(self):
        config = {"tools": {}}
        trainer = LichtfeldTrainer(config)
        ok, msg = trainer.validate_environment()
        assert ok is False

    def test_parse_progress_iteration(self):
        trainer = LichtfeldTrainer({})
        assert trainer.parse_progress("Iteration 1000/30000") == pytest.approx(1000/30000)
        assert trainer.parse_progress("iteration 15000/30000") == pytest.approx(0.5)
        assert trainer.parse_progress("Other text") is None

    def test_max_cap_uses_actual_count(self, tmp_path):
        """Verify --max-cap gets actual splat count, not kSplats."""
        fake_exe = tmp_path / "lichtfeld"
        fake_exe.write_text("")
        config = {"tools": {"lichtfeld_studio": str(fake_exe)}}
        trainer = LichtfeldTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            gen = trainer.train_lod(
                tmp_path / "colmap", tmp_path / "output",
                "lod0_3000k", 3_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--max-cap")
        # LichtFeld uses actual count
        assert cmd[idx + 1] == "3000000"

    def test_strategy_from_config(self, tmp_path):
        """Strategy comes from config."""
        fake_exe = tmp_path / "lichtfeld"
        fake_exe.write_text("")
        config = {
            "tools": {"lichtfeld_studio": str(fake_exe)},
            "lichtfeld": {"strategy": "3dgs", "iterations": 50000},
        }
        trainer = LichtfeldTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            gen = trainer.train_lod(
                tmp_path / "colmap", tmp_path / "output",
                "lod0_3000k", 3_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        assert "--strategy" in cmd
        idx = cmd.index("--strategy")
        assert cmd[idx + 1] == "3dgs"
        idx = cmd.index("-i")
        assert cmd[idx + 1] == "50000"
