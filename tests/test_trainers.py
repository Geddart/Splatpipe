"""Tests for trainer abstraction, Postshot, and LichtFeld trainers."""

import io
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from splatpipe.trainers.postshot import PostshotTrainer
from splatpipe.trainers.lichtfeld import LichtfeldTrainer
from splatpipe.trainers.passthrough import PassthroughTrainer
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

    def test_get_passthrough(self):
        config = {"tools": {}}
        trainer = get_trainer("passthrough", config)
        assert isinstance(trainer, PassthroughTrainer)
        assert trainer.name == "passthrough"

    def test_list_trainers_includes_passthrough(self):
        assert "passthrough" in list_trainers()

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
        # v1.0.287+ flags not present by default
        assert "--gpu" not in cmd
        assert "--max-sh-degree" not in cmd
        assert "--pose-quality" not in cmd
        assert "--no-recenter-points" not in cmd
        assert "--image-select" not in cmd

    def test_profile_splat_adc(self, tmp_path):
        """Splat ADC profile uses --splat-density instead of --max-num-splats."""
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
                "lod0", 3_000_000,
                profile="Splat ADC", splat_density=2.5,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        assert "--max-num-splats" not in cmd
        idx = cmd.index("--splat-density")
        assert cmd[idx + 1] == "2.5"
        idx = cmd.index("-p")
        assert cmd[idx + 1] == "Splat ADC"

    def test_gpu_selection(self, tmp_path):
        """GPU index passed when >= 0."""
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
                "lod0", 3_000_000, gpu=1,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--gpu")
        assert cmd[idx + 1] == "1"

    def test_max_sh_degree(self, tmp_path):
        """Max SH degree passed when non-default."""
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
                "lod0", 3_000_000, max_sh_degree=1,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--max-sh-degree")
        assert cmd[idx + 1] == "1"

    def test_pose_quality(self, tmp_path):
        """--pose-quality passed when non-default via kwargs (Postshot v1.0.331+)."""
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
                "lod0", 3_000_000, pose_quality=4,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--pose-quality")
        assert cmd[idx + 1] == "4"

    def test_pose_quality_from_config(self, tmp_path):
        """--pose-quality passed when non-default via config (no kwargs)."""
        config = _postshot_config(tmp_path)
        config["postshot"] = {"pose_quality": 1}
        trainer = PostshotTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = io.StringIO("")
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        mock_proc.poll.return_value = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            gen = trainer.train_lod(
                tmp_path / "colmap", tmp_path / "output",
                "lod0", 3_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--pose-quality")
        assert cmd[idx + 1] == "1"

    def test_no_recenter_points(self, tmp_path):
        """--no-recenter-points flag added when enabled."""
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
                "lod0", 3_000_000, no_recenter_points=True,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        assert "--no-recenter-points" in cmd

    def test_image_select_best(self, tmp_path):
        """--image-select best with --num-train-images."""
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
                "lod0", 3_000_000,
                image_select="best", num_train_images=200,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--image-select")
        assert cmd[idx + 1] == "best"
        idx = cmd.index("--num-train-images")
        assert cmd[idx + 1] == "200"

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

    def test_stderr_merged_into_stdout(self, tmp_path):
        """Regression: stderr must merge into stdout so a full stderr buffer
        can't deadlock the process while we're only consuming stdout."""
        fake_root = tmp_path / "lichtfeld"
        fake_exe = fake_root / "bin" / "LichtFeld-Studio.exe"
        fake_exe.parent.mkdir(parents=True)
        fake_exe.write_text("")
        config = {"tools": {"lichtfeld_studio": str(fake_root)}}
        trainer = LichtfeldTrainer(config)

        mock_proc = MagicMock()
        mock_proc.stdout = io.StringIO("")
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            gen = trainer.train_lod(
                tmp_path / "colmap", tmp_path / "output",
                "lod0", 1_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        _args, kwargs = mock_popen.call_args
        assert kwargs.get("stderr") is subprocess.STDOUT, (
            "Lichtfeld trainer must merge stderr into stdout to avoid buffer deadlock"
        )

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

    def test_headless_and_train_flags(self, tmp_path):
        """--headless and --train always present in CLI command."""
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
                "lod0", 3_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        assert "--headless" in cmd
        assert "--train" in cmd

    def test_ppisp_enabled(self, tmp_path):
        """--ppisp flag added when config is true."""
        fake_root = tmp_path / "lichtfeld"
        fake_exe = fake_root / "bin" / "LichtFeld-Studio.exe"
        fake_exe.parent.mkdir(parents=True)
        fake_exe.write_text("")
        config = {
            "tools": {"lichtfeld_studio": str(fake_root)},
            "lichtfeld": {"ppisp": True},
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
                "lod0", 3_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        assert "--ppisp" in cmd

    def test_ppisp_controller(self, tmp_path):
        """--ppisp-controller flag added when config is true."""
        fake_root = tmp_path / "lichtfeld"
        fake_exe = fake_root / "bin" / "LichtFeld-Studio.exe"
        fake_exe.parent.mkdir(parents=True)
        fake_exe.write_text("")
        config = {
            "tools": {"lichtfeld_studio": str(fake_root)},
            "lichtfeld": {"ppisp": True, "ppisp_controller": True},
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
                "lod0", 3_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        assert "--ppisp" in cmd
        assert "--ppisp-controller" in cmd

    def test_ppisp_disabled_by_default(self, tmp_path):
        """PPISP flags not present when not configured."""
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
                "lod0", 3_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        assert "--ppisp" not in cmd
        assert "--ppisp-controller" not in cmd

    def test_sh_degree(self, tmp_path):
        """--sh-degree passed when non-default."""
        fake_root = tmp_path / "lichtfeld"
        fake_exe = fake_root / "bin" / "LichtFeld-Studio.exe"
        fake_exe.parent.mkdir(parents=True)
        fake_exe.write_text("")
        config = {
            "tools": {"lichtfeld_studio": str(fake_root)},
            "lichtfeld": {"sh_degree": 1},
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
                "lod0", 3_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--sh-degree")
        assert cmd[idx + 1] == "1"

    def test_enable_mip(self, tmp_path):
        """--enable-mip flag added when configured."""
        fake_root = tmp_path / "lichtfeld"
        fake_exe = fake_root / "bin" / "LichtFeld-Studio.exe"
        fake_exe.parent.mkdir(parents=True)
        fake_exe.write_text("")
        config = {
            "tools": {"lichtfeld_studio": str(fake_root)},
            "lichtfeld": {"enable_mip": True},
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
                "lod0", 3_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        assert "--enable-mip" in cmd

    def test_tile_mode(self, tmp_path):
        """--tile-mode passed when non-default."""
        fake_root = tmp_path / "lichtfeld"
        fake_exe = fake_root / "bin" / "LichtFeld-Studio.exe"
        fake_exe.parent.mkdir(parents=True)
        fake_exe.write_text("")
        config = {
            "tools": {"lichtfeld_studio": str(fake_root)},
            "lichtfeld": {"tile_mode": 4},
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
                "lod0", 3_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--tile-mode")
        assert cmd[idx + 1] == "4"

    def test_max_width(self, tmp_path):
        """--max-width passed when non-default."""
        fake_root = tmp_path / "lichtfeld"
        fake_exe = fake_root / "bin" / "LichtFeld-Studio.exe"
        fake_exe.parent.mkdir(parents=True)
        fake_exe.write_text("")
        config = {
            "tools": {"lichtfeld_studio": str(fake_root)},
            "lichtfeld": {"max_width": 1920},
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
                "lod0", 3_000_000,
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--max-width")
        assert cmd[idx + 1] == "1920"


class TestPassthroughTrainer:
    def test_validate_environment_ok(self):
        """Passthrough defers tool checks to runtime — always returns ok."""
        trainer = PassthroughTrainer({})
        ok, msg = trainer.validate_environment()
        assert ok is True

    def test_parse_progress_returns_none(self):
        """Passthrough has no parseable progress."""
        trainer = PassthroughTrainer({})
        assert trainer.parse_progress("anything") is None

    @staticmethod
    def _fake_psht_proc(stdout_text="export ok\n", returncode=0):
        """Build a mock Popen proc that works with the reader-thread pattern.

        The reader thread does `for line in iter(proc.stdout.readline, "")`, so
        stdout must be a real stream-like object whose readline() eventually
        returns ''. io.StringIO does exactly that.
        """
        proc = MagicMock()
        proc.stdout = io.StringIO(stdout_text)
        proc.returncode = returncode
        proc.poll.return_value = returncode  # process already exited
        proc.wait.return_value = None
        return proc

    def test_psht_source_runs_postshot_export(self, tmp_path):
        """`.psht` input runs `postshot-cli export -f source --export-splat out`."""
        config = _postshot_config(tmp_path)
        trainer = PassthroughTrainer(config)
        psht = tmp_path / "scene.psht"
        psht.write_bytes(b"\x00")
        out_dir = tmp_path / "training"

        mock_proc = self._fake_psht_proc()

        # Make the output PLY appear (real Postshot would write it).
        def fake_popen(cmd, *args, **kwargs):
            ply_arg = cmd[cmd.index("--export-splat") + 1]
            from pathlib import Path as _P
            _P(ply_arg).write_bytes(b"ply\n")
            return mock_proc

        with patch("splatpipe.trainers.passthrough.subprocess.Popen",
                   side_effect=fake_popen) as mock_popen, \
             patch("splatpipe.trainers.passthrough.time.sleep", return_value=None):
            gen = trainer.train_lod(psht, out_dir, "lod0", 0)
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        cmd = mock_popen.call_args[0][0]
        assert "export" in cmd
        assert "-f" in cmd
        assert str(psht) in cmd
        assert "--export-splat" in cmd
        assert result.success is True
        assert result.output_ply.endswith("lod0.ply")
        assert result.returncode == 0

    def test_ply_source_copies_file(self, tmp_path):
        """`.ply` input is copied straight to the output."""
        trainer = PassthroughTrainer({})
        ply = tmp_path / "scene.ply"
        ply.write_bytes(b"ply\nformat ascii 1.0\nend_header\n")
        out_dir = tmp_path / "training"

        gen = trainer.train_lod(ply, out_dir, "lod0", 0)
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        out_ply = out_dir / "lod0.ply"
        assert out_ply.exists()
        assert out_ply.read_bytes() == ply.read_bytes()
        assert result.success is True
        assert result.output_ply == str(out_ply)

    def test_unknown_extension_returns_failure(self, tmp_path):
        """Unsupported source extension yields a failure result, no exception."""
        trainer = PassthroughTrainer({})
        bogus = tmp_path / "scene.obj"
        bogus.write_text("# obj")
        out_dir = tmp_path / "training"

        gen = trainer.train_lod(bogus, out_dir, "lod0", 0)
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result.success is False
        assert ".obj" in result.stderr or "Passthrough requires" in result.stderr
        assert result.output_ply == ""

    def test_psht_path_does_not_block_on_communicate(self, tmp_path):
        """Regression: the .psht branch must not call Popen.communicate() —
        that call blocks the generator and prevents the runner from cancelling
        during a long Postshot export. Check the source contains the
        reader-thread pattern instead, not the blocking .communicate() call.
        """
        import inspect
        import re
        from splatpipe.trainers import passthrough as passthrough_mod
        src = inspect.getsource(passthrough_mod.PassthroughTrainer.train_lod)
        # Strip comments first so a comment mentioning communicate() doesn't
        # fool the check.
        src_code = re.sub(r"(?m)^\s*#.*$", "", src)
        assert ".communicate(" not in src_code, (
            "PassthroughTrainer must not call Popen.communicate() — use a "
            "reader thread + periodic yields so cancel can fire during extraction."
        )
        # And the expected pattern is present:
        assert "queue.Queue" in src_code
        assert "threading.Thread" in src_code

    def test_postshot_failure_returns_failure(self, tmp_path):
        """Non-zero return code from postshot-cli surfaces as failure."""
        config = _postshot_config(tmp_path)
        trainer = PassthroughTrainer(config)
        psht = tmp_path / "scene.psht"
        psht.write_bytes(b"\x00")
        out_dir = tmp_path / "training"

        mock_proc = self._fake_psht_proc(stdout_text="error\n", returncode=1)
        with patch("splatpipe.trainers.passthrough.subprocess.Popen",
                   return_value=mock_proc), \
             patch("splatpipe.trainers.passthrough.time.sleep", return_value=None):
            gen = trainer.train_lod(psht, out_dir, "lod0", 0)
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result.success is False
        assert result.returncode == 1
