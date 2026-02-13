"""Tests for export_to_folder: file copying with progress events."""

import pytest

from splatpipe.steps.deploy import export_to_folder
from splatpipe.core.events import ProgressEvent, StepResult


def _consume_generator(gen):
    """Consume a generator, collecting events and returning the final result."""
    events = []
    try:
        while True:
            events.append(next(gen))
    except StopIteration as e:
        return events, e.value


def test_export_copies_files(tmp_path):
    """export_to_folder copies all files to destination."""
    output = tmp_path / "output"
    output.mkdir()
    (output / "a.txt").write_text("hello")
    (output / "b.txt").write_text("world")

    dest = tmp_path / "dest"
    events, result = _consume_generator(export_to_folder(output, dest))

    assert result.success
    assert (dest / "a.txt").read_text() == "hello"
    assert (dest / "b.txt").read_text() == "world"


def test_export_creates_destination(tmp_path):
    """export_to_folder creates destination directory if missing."""
    output = tmp_path / "output"
    output.mkdir()
    (output / "file.txt").write_text("data")

    dest = tmp_path / "new" / "nested" / "dir"
    events, result = _consume_generator(export_to_folder(output, dest))

    assert result.success
    assert dest.is_dir()
    assert (dest / "file.txt").read_text() == "data"


def test_export_preserves_directory_structure(tmp_path):
    """export_to_folder preserves subdirectory structure."""
    output = tmp_path / "output"
    (output / "sub" / "deep").mkdir(parents=True)
    (output / "root.txt").write_text("root")
    (output / "sub" / "nested.txt").write_text("nested")
    (output / "sub" / "deep" / "deep.txt").write_text("deep")

    dest = tmp_path / "dest"
    events, result = _consume_generator(export_to_folder(output, dest))

    assert result.success
    assert (dest / "root.txt").read_text() == "root"
    assert (dest / "sub" / "nested.txt").read_text() == "nested"
    assert (dest / "sub" / "deep" / "deep.txt").read_text() == "deep"


def test_export_yields_progress_events(tmp_path):
    """export_to_folder yields ProgressEvent per file."""
    output = tmp_path / "output"
    output.mkdir()
    for i in range(5):
        (output / f"file{i}.txt").write_text(f"data{i}")

    dest = tmp_path / "dest"
    events, result = _consume_generator(export_to_folder(output, dest))

    assert len(events) == 6  # 1 initial + 5 per-file
    assert all(isinstance(e, ProgressEvent) for e in events)
    assert events[0].progress == 0.0
    assert events[-1].progress == 1.0


def test_export_result_summary(tmp_path):
    """export_to_folder returns correct summary."""
    output = tmp_path / "output"
    output.mkdir()
    (output / "a.bin").write_bytes(b"x" * 1000)
    (output / "b.bin").write_bytes(b"y" * 2000)

    dest = tmp_path / "dest"
    events, result = _consume_generator(export_to_folder(output, dest))

    assert result.success
    assert result.summary["copied"] == 2
    assert result.summary["total_files"] == 2
    assert result.summary["destination"] == str(dest)
    assert result.summary["total_mb"] == pytest.approx(0.0, abs=0.01)
    assert "duration_s" in result.summary


def test_export_empty_output_dir(tmp_path):
    """export_to_folder fails gracefully with empty output directory."""
    output = tmp_path / "output"
    output.mkdir()  # empty

    dest = tmp_path / "dest"
    gen = export_to_folder(output, dest)

    # Should return immediately with failure (no events yielded)
    try:
        next(gen)
        pytest.fail("Expected StopIteration for empty dir")
    except StopIteration as e:
        result = e.value
        assert not result.success
        assert "No files" in result.error
