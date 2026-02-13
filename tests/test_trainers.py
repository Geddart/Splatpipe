"""Tests for trainer abstraction, Postshot, and LichtFeld trainers."""

import io
from unittest.mock import patch, MagicMock

import pytest

from splatpipe.trainers.postshot import PostshotTrainer
from splatpipe.trainers.lichtfeld import LichtfeldTrainer
from splatpipe.trainers.registry import get_trainer, list_trainers


def _postshot_config(tmp_path):
    """Create a fake Postshot root folder with bin/postshot-cli.exe."""
    bin_dir = tmp_path / "postshot" / "bin"
    bin_dir.mkdir(parents=True)
    fake_cli = bin_dir / "postshot-cli.exe"
    fake_cli.write_text("")
    return {"tools": {"postshot": str(bin_dir.parent)}}


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
        config = {"tools": {"postshot": r"C:\nonexistent\folder"}}
        trainer = PostshotTrainer(config)
        ok, msg = trainer.validate_environment()
        assert ok is False
        assert "not found" in msg.lower()

    def test_validate_exists(self, tmp_path):
        config = _postshot_config(tmp_path)
        trainer = PostshotTrainer(config)
        ok, msg = trainer.validate_environment()
        assert ok is True

    def test_parse_progress_step_legacy(self):
        """Legacy 'Step X/Y' format still works."""
        trainer = PostshotTrainer({})
        assert trainer.parse_progress("Step 100/5000") == pytest.approx(0.02)
        assert trainer.parse_progress("step 2500/5000") == pytest.approx(0.5)
        assert trainer.parse_progress("Step 5000/5000") == pytest.approx(1.0)
        assert trainer.parse_progress("Some other line") is None

    def test_parse_progress_v1_format(self):
        """Postshot v1.0.185+ 'Training Radiance Field' format."""
        trainer = PostshotTrainer({})
        line = (
            "Training Radiance Field: 2%, Elapsed: 1 s, Remaining: 3 m 19 s, "
            "46 Steps of 2.00 kSteps, 1.38 MSplats"
        )
        result = trainer.parse_progress(line)
        # 46 steps / 2000 total = 0.023
        assert result == pytest.approx(46 / 2000)

        # Also test the dict from _parse_step_line
        parsed = trainer._parse_step_line(line)
        assert parsed is not None
        assert parsed["pct"] == 2
        assert parsed["steps"] == 46
        assert parsed["total_ksteps"] == pytest.approx(2.0)
        assert parsed["msplats"] == pytest.approx(1.38)

    def test_parse_progress_v1_high_percent(self):
        """v1 format at higher progress."""
        trainer = PostshotTrainer({})
        line = (
            "Training Radiance Field: 85%, Elapsed: 3 m 2 s, Remaining: 32 s, "
            "1700 Steps of 2.00 kSteps, 4.92 MSplats"
        )
        assert trainer.parse_progress(line) == pytest.approx(1700 / 2000)

    def test_parse_progress_v1_ksteps_format(self):
        """v1 format switches to kSteps for current step count after 999."""
        trainer = PostshotTrainer({})
        # At 1.924 kSteps (= 1924 steps)
        line = (
            "Training Radiance Field: 96%, Elapsed: 55 s, Remaining: 2 s, "
            "1.924 kSteps of 2.00 kSteps, 2.23 MSplats"
        )
        parsed = trainer._parse_step_line(line)
        assert parsed is not None
        assert parsed["steps"] == 1924
        assert parsed["total_ksteps"] == pytest.approx(2.0)
        assert parsed["total_steps"] == 2000
        assert trainer.parse_progress(line) == pytest.approx(1924 / 2000)

        # At 50.000 kSteps (= 50000 steps)
        line2 = (
            "Training Radiance Field: 100%, Elapsed: 5 m, "
            "50.000 kSteps of 50.00 kSteps, 5.00 MSplats"
        )
        assert trainer.parse_progress(line2) == pytest.approx(1.0)

    def test_auto_train_steps_from_num_images(self, tmp_path):
        """When train_steps_limit=0 and num_images>0, auto-compute steps."""
        config = _postshot_config(tmp_path)
        trainer = PostshotTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = io.StringIO("")
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        mock_proc.poll.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            gen = trainer.train_lod(
                tmp_path / "colmap", tmp_path / "output",
                "lod0_3000k", 3_000_000,
                num_images=5000,  # -> max(50, round(5000*52/1000)) = 260 kSteps
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("-s")
        assert cmd[idx + 1] == "260"

    def test_compute_training_steps(self):
        trainer = PostshotTrainer({})
        # 500 images -> max(50, round(500*52/1000)) = max(50, 26) = 50
        assert trainer.compute_training_steps(500) == 50
        # 2000 images -> max(50, round(2000*52/1000)) = max(50, 104) = 104
        assert trainer.compute_training_steps(2000) == 104

    def test_train_lod_with_mock(self, tmp_path):
        """Train a LOD with mocked Popen (legacy Step X/Y format)."""
        import io
        config = _postshot_config(tmp_path)
        trainer = PostshotTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = io.StringIO(
            "Step 1/100\nStep 50/100\nStep 100/100\n"
        )
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        mock_proc.poll.return_value = 0

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
        # Should have initial event + heartbeat events with parsed progress
        assert len(events) >= 2
        # Last event should have the final progress
        assert events[-1].sub_progress == pytest.approx(1.0)

    def test_train_lod_v1_format(self, tmp_path):
        """Train a LOD with v1.0.185 output format."""
        import io
        config = _postshot_config(tmp_path)
        trainer = PostshotTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = io.StringIO(
            "Training Radiance Field: 50%, Elapsed: 1 m 30 s, Remaining: 1 m 30 s, "
            "1000 Steps of 2.00 kSteps, 3.00 MSplats\n"
            "Training Radiance Field: 100%, Elapsed: 3 m, Remaining: 0 s, "
            "2000 Steps of 2.00 kSteps, 3.00 MSplats\n"
        )
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        mock_proc.poll.return_value = 0

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
        assert result.success is True
        assert len(events) >= 2
        assert events[-1].sub_progress == pytest.approx(1.0)
        # Message should include step count and splat info
        assert "Step" in events[-1].message
        assert "MSplats" in events[-1].message or "M splats" in events[-1].message

    def test_train_lod_failure(self, tmp_path):
        """Non-zero exit code produces failed TrainResult."""
        import io
        config = _postshot_config(tmp_path)
        trainer = PostshotTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = io.StringIO("")
        mock_proc.returncode = 1
        mock_proc.wait.return_value = None
        mock_proc.poll.return_value = 1

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

    def test_ksplats_conversion(self, tmp_path):
        """Verify CLI gets kSplats not raw splat count."""
        config = _postshot_config(tmp_path)
        trainer = PostshotTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = io.StringIO("")
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


    def test_train_kwargs_cli_args(self, tmp_path):
        """Verify kwargs produce correct CLI flags."""
        config = _postshot_config(tmp_path)
        trainer = PostshotTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = io.StringIO("")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            gen = trainer.train_lod(
                tmp_path / "colmap", tmp_path / "output",
                "lod0_3000k", 3_000_000,
                profile="Splat MCMC",
                downsample=True,
                max_image_size=1920,
                anti_aliasing=True,
                create_sky_model=True,
                train_steps_limit=150,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        # Profile
        idx = cmd.index("-p")
        assert cmd[idx + 1] == "Splat MCMC"
        # Downsample
        idx = cmd.index("--max-image-size")
        assert cmd[idx + 1] == "1920"
        # Anti-aliasing
        idx = cmd.index("--anti-aliasing")
        assert cmd[idx + 1] == "true"
        # Sky model
        assert "--create-sky-model" in cmd
        # Train steps
        idx = cmd.index("-s")
        assert cmd[idx + 1] == "150"

    def test_train_kwargs_defaults(self, tmp_path):
        """Verify omitted kwargs produce sensible defaults (no extra flags)."""
        config = _postshot_config(tmp_path)
        trainer = PostshotTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = io.StringIO("")
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
        # Default profile is Splat3
        idx = cmd.index("-p")
        assert cmd[idx + 1] == "Splat3"
        # Anti-aliasing should NOT be in cmd by default
        assert "--anti-aliasing" not in cmd
        # Sky model should NOT be in cmd by default
        assert "--create-sky-model" not in cmd
        # Train steps limit should NOT be in cmd (0 = auto)
        assert "-s" not in cmd

    def test_train_downsample_off(self, tmp_path):
        """Verify downsample=False passes --max-image-size 0."""
        config = _postshot_config(tmp_path)
        trainer = PostshotTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = io.StringIO("")
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            gen = trainer.train_lod(
                tmp_path / "colmap", tmp_path / "output",
                "lod0_3000k", 3_000_000,
                downsample=False,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--max-image-size")
        assert cmd[idx + 1] == "0"


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
        fake_root = tmp_path / "lichtfeld"
        fake_exe = fake_root / "bin" / "LichtFeld-Studio.exe"
        fake_exe.parent.mkdir(parents=True)
        fake_exe.write_text("")
        config = {"tools": {"lichtfeld_studio": str(fake_root)}}
        trainer = LichtfeldTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = io.StringIO("")
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
        fake_root = tmp_path / "lichtfeld"
        fake_exe = fake_root / "bin" / "LichtFeld-Studio.exe"
        fake_exe.parent.mkdir(parents=True)
        fake_exe.write_text("")
        config = {
            "tools": {"lichtfeld_studio": str(fake_root)},
            "lichtfeld": {"strategy": "3dgs", "iterations": 50000},
        }
        trainer = LichtfeldTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = io.StringIO("")
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
