"""Tests for ProgressEvent and StepResult dataclasses."""


from splatpipe.core.events import ProgressEvent, StepResult, ProgressGenerator


class TestProgressEvent:
    def test_defaults(self):
        """ProgressEvent has sensible defaults for optional fields."""
        evt = ProgressEvent(step="clean", progress=0.5)
        assert evt.step == "clean"
        assert evt.progress == 0.5
        assert evt.message == ""
        assert evt.detail == ""
        assert evt.sub_step == ""
        assert evt.sub_progress == 0.0

    def test_all_fields(self):
        """All fields can be set explicitly."""
        evt = ProgressEvent(
            step="train", progress=0.75,
            message="Training LOD 2", detail="1500/2000 steps",
            sub_step="lod1_1500k", sub_progress=0.8,
        )
        assert evt.step == "train"
        assert evt.progress == 0.75
        assert evt.message == "Training LOD 2"
        assert evt.detail == "1500/2000 steps"
        assert evt.sub_step == "lod1_1500k"
        assert evt.sub_progress == 0.8


class TestStepResult:
    def test_success_defaults(self):
        """StepResult defaults: empty summary, no error."""
        result = StepResult(step="clean", success=True)
        assert result.step == "clean"
        assert result.success is True
        assert result.summary == {}
        assert result.error is None
        assert result.debug_path is None

    def test_failure_with_error(self):
        """Failed StepResult carries error message."""
        result = StepResult(
            step="train", success=False,
            error="CUDA out of memory",
        )
        assert result.success is False
        assert result.error == "CUDA out of memory"

    def test_summary_is_independent(self):
        """Each StepResult gets its own summary dict (not shared default)."""
        r1 = StepResult(step="a", success=True)
        r2 = StepResult(step="b", success=True)
        r1.summary["key"] = "value"
        assert "key" not in r2.summary


class TestProgressGenerator:
    def test_type_alias_is_generator(self):
        """ProgressGenerator is a Generator type alias."""
        import collections.abc
        assert ProgressGenerator.__origin__ is collections.abc.Generator
