"""Shared test fixtures."""

import shutil
from pathlib import Path

import pytest

TEST_DATA = Path(__file__).parent / "test_data"


@pytest.fixture
def test_data_dir():
    return TEST_DATA


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory with test COLMAP data."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()

    # Create COLMAP source folder with test data
    colmap_dir = project_dir / "01_colmap_source"
    colmap_dir.mkdir()
    shutil.copy(TEST_DATA / "tiny_cameras.txt", colmap_dir / "cameras.txt")
    shutil.copy(TEST_DATA / "tiny_images.txt", colmap_dir / "images.txt")
    shutil.copy(TEST_DATA / "tiny_points3d.txt", colmap_dir / "points3D.txt")
    shutil.copy(TEST_DATA / "tiny_cloud.ply", colmap_dir / "cloud.ply")

    # Create output folder
    (project_dir / "02_colmap_clean").mkdir()

    return project_dir


@pytest.fixture
def tiny_cameras_path(test_data_dir):
    return test_data_dir / "tiny_cameras.txt"


@pytest.fixture
def tiny_images_path(test_data_dir):
    return test_data_dir / "tiny_images.txt"


@pytest.fixture
def tiny_points3d_path(test_data_dir):
    return test_data_dir / "tiny_points3d.txt"


@pytest.fixture
def tiny_ply_path(test_data_dir):
    return test_data_dir / "tiny_cloud.ply"
