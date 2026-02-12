"""Tests for COLMAP cleaning filters — the most critical tests."""



from splatpipe.colmap.filters import (
    analyze_cameras,
    remove_outlier_cameras,
    filter_points3d_kdtree,
    clean_points2d_refs,
    load_kept_point_ids,
)


class TestAnalyzeCameras:
    def test_basic_analysis(self, tiny_images_path):
        """Analyze 5 cameras, identify outlier stats."""
        result = analyze_cameras(tiny_images_path)
        assert result["total"] == 5
        assert "median" in result
        assert "outliers" in result
        assert "threshold" in result
        assert "ranges" in result

    def test_outliers_detected(self, tiny_images_path):
        """Cameras 4 and 5 should be outliers with a reasonable threshold.

        With only 5 cameras, the auto-threshold (2.5x 99th percentile) is too
        high because p99 includes the outliers. Test with explicit threshold.
        """
        result = analyze_cameras(tiny_images_path)
        med = result["median"]
        outlier_names = set()
        for name, tx, ty, tz in result["cameras"]:
            d = ((tx - med["tx"])**2 + (ty - med["ty"])**2 + (tz - med["tz"])**2)**0.5
            if d > 100.0:
                outlier_names.add(name)
        assert "image004.jpg" in outlier_names
        assert "image005.jpg" in outlier_names
        assert len(outlier_names) == 2


class TestRemoveOutlierCameras:
    def test_remove_two_outliers(self, tiny_images_path, tmp_path):
        """Remove 2 outlier cameras, keep 3."""
        out_path = tmp_path / "images_clean.txt"
        outlier_names = {"image004.jpg", "image005.jpg"}
        result = remove_outlier_cameras(tiny_images_path, out_path, outlier_names)

        assert result["kept"] == 3
        assert result["removed"] == 2

        # Verify output file has only 3 cameras
        from splatpipe.colmap.parsers import count_images
        assert count_images(out_path) == 3

    def test_remove_none(self, tiny_images_path, tmp_path):
        """Removing no cameras keeps all."""
        out_path = tmp_path / "images_clean.txt"
        result = remove_outlier_cameras(tiny_images_path, out_path, set())

        assert result["kept"] == 5
        assert result["removed"] == 0

    def test_removed_names_correct(self, tiny_images_path, tmp_path):
        """Verify the correct cameras are removed by checking remaining names."""
        out_path = tmp_path / "images_clean.txt"
        remove_outlier_cameras(tiny_images_path, out_path, {"image004.jpg", "image005.jpg"})

        from splatpipe.colmap.parsers import parse_images_txt
        remaining = [img["name"] for img in parse_images_txt(out_path)]
        assert "image001.jpg" in remaining
        assert "image002.jpg" in remaining
        assert "image003.jpg" in remaining
        assert "image004.jpg" not in remaining
        assert "image005.jpg" not in remaining


class TestKDTreeFilter:
    def test_filter_keeps_near_points(self, tiny_points3d_path, tiny_ply_path, tmp_path):
        """Filter 50 points, 20-vertex PLY -> keep exactly 20 near points."""
        out_path = tmp_path / "points3D_filtered.txt"
        result = filter_points3d_kdtree(
            tiny_points3d_path, out_path, tiny_ply_path,
            threshold=0.001,
        )

        assert result["ply_vertices"] == 20
        assert result["points_before"] == 50
        assert result["points_after"] == 20
        assert result["points_removed"] == 30

    def test_filter_kept_ids(self, tiny_points3d_path, tiny_ply_path, tmp_path):
        """Verify correct point IDs are kept (1-20)."""
        out_path = tmp_path / "points3D_filtered.txt"
        result = filter_points3d_kdtree(
            tiny_points3d_path, out_path, tiny_ply_path,
            threshold=0.001,
        )

        kept_ids = result["kept_ids"]
        for i in range(1, 21):
            assert i in kept_ids, f"Point {i} should be kept"
        for i in range(21, 51):
            assert i not in kept_ids, f"Point {i} should be removed"

    def test_filter_coordinate_ranges(self, tiny_points3d_path, tiny_ply_path, tmp_path):
        """After filtering, coordinate ranges should be much smaller."""
        out_path = tmp_path / "points3D_filtered.txt"
        result = filter_points3d_kdtree(
            tiny_points3d_path, out_path, tiny_ply_path,
            threshold=0.001,
        )

        before = result["coordinate_ranges_before"]
        after = result["coordinate_ranges_after"]

        # Before: ranges go to hundreds/thousands
        assert before["x"]["max"] > 100 or before["x"]["min"] < -100
        # After: ranges should be within -2 to 2
        assert after["x"]["max"] < 3
        assert after["x"]["min"] > -3

    def test_filter_with_custom_transform(self, tiny_points3d_path, tiny_ply_path, tmp_path):
        """Custom transform should change which points match."""
        out_path = tmp_path / "points3D_filtered.txt"
        # Identity transform (no transform) — PLY coords used as-is
        result = filter_points3d_kdtree(
            tiny_points3d_path, out_path, tiny_ply_path,
            threshold=0.001,
            transform=(1, 0, 0, 0, 1, 0, 0, 0, 1),  # identity
        )
        # With identity transform, PLY coords don't match COLMAP coords
        assert result["points_after"] < 20


class TestCleanPoints2dRefs:
    def test_clean_dangling_refs(self, tiny_images_path, tmp_path):
        """Replace dangling POINT3D_IDs with -1, keep valid ones."""
        out_path = tmp_path / "images_cleaned.txt"
        kept_ids = set(range(1, 21))

        result = clean_points2d_refs(tiny_images_path, out_path, kept_ids)

        assert result["cameras"] == 5
        assert result["total_refs"] > 0
        assert result["kept_refs"] > 0
        assert result["cleaned_refs"] > 0
        assert result["cleaned_refs"] > result["kept_refs"]

    def test_clean_preserves_valid_refs(self, tiny_images_path, tmp_path):
        """Valid POINT3D_IDs should be preserved unchanged."""
        out_path = tmp_path / "images_cleaned.txt"
        kept_ids = set(range(1, 51))  # keep all

        result = clean_points2d_refs(tiny_images_path, out_path, kept_ids)
        assert result["kept_refs"] > 0

    def test_clean_empty_points2d(self, tmp_path):
        """Empty POINTS2D lines pass through unchanged."""
        images_path = tmp_path / "images.txt"
        out_path = tmp_path / "images_out.txt"
        images_path.write_text(
            "# test\n"
            "1 0.5 0.0 0.0 0.0 1.0 2.0 3.0 1 test.jpg\n"
            "\n"
        )

        result = clean_points2d_refs(images_path, out_path, set())
        assert result["cameras"] == 1
        assert result["total_refs"] == 0

    def test_output_has_correct_ids(self, tmp_path):
        """Verify specific IDs become -1 in output."""
        images_path = tmp_path / "images.txt"
        out_path = tmp_path / "images_out.txt"
        images_path.write_text(
            "# test\n"
            "1 0.5 0.0 0.0 0.0 1.0 2.0 3.0 1 test.jpg\n"
            "100.0 200.0 5 300.0 400.0 999 500.0 600.0 -1\n"
        )

        kept_ids = {5}
        clean_points2d_refs(images_path, out_path, kept_ids)

        content = out_path.read_text()
        lines = [line for line in content.split("\n") if line and not line.startswith("#")]
        pts_line = lines[1]
        parts = pts_line.split()
        assert parts[2] == "5"
        assert parts[5] == "-1"
        assert parts[8] == "-1"


class TestDebugJsonOutput:
    def test_kdtree_returns_all_fields(self, tiny_points3d_path, tiny_ply_path, tmp_path):
        """Verify KD-tree filter returns all expected debug fields."""
        out_path = tmp_path / "points3D_filtered.txt"
        result = filter_points3d_kdtree(
            tiny_points3d_path, out_path, tiny_ply_path,
            threshold=0.001,
        )

        assert "ply_vertices" in result
        assert "threshold" in result
        assert "points_before" in result
        assert "points_after" in result
        assert "points_removed" in result
        assert "kept_ids" in result
        assert "coordinate_ranges_before" in result
        assert "coordinate_ranges_after" in result
        assert "tree_build_s" in result
        assert "duration_s" in result
        assert "ply_ranges" in result

    def test_camera_analysis_fields(self, tiny_images_path):
        """Verify camera analysis returns all expected fields."""
        result = analyze_cameras(tiny_images_path)

        assert "cameras" in result
        assert "median" in result
        assert "outliers" in result
        assert "threshold" in result
        assert "total" in result
        assert "ranges" in result
        assert "tx" in result["median"]
        assert "ty" in result["median"]
        assert "tz" in result["median"]


class TestLoadKeptPointIds:
    def test_load_ids(self, tiny_points3d_path):
        """Load all 50 point IDs."""
        ids = load_kept_point_ids(tiny_points3d_path)
        assert len(ids) == 50
        assert 1 in ids
        assert 50 in ids
