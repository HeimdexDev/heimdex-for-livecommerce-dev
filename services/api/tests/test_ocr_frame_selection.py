import importlib.util
from pathlib import Path

_ocr_module_path = Path(__file__).resolve().parents[2] / "drive-ocr-worker" / "src" / "tasks" / "ocr.py"
_spec = importlib.util.spec_from_file_location("_ocr_tasks_for_test", _ocr_module_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
select_keyframe_indices = _mod.select_keyframe_indices


class TestSelectKeyframeIndices:
    def test_empty_scenes(self):
        assert select_keyframe_indices(0, 10) == []

    def test_single_scene(self):
        assert select_keyframe_indices(1, 10) == [0]

    def test_all_within_cap(self):
        assert select_keyframe_indices(3, 10) == [0, 1, 2]

    def test_exact_cap(self):
        assert select_keyframe_indices(10, 10) == list(range(10))

    def test_over_cap_evenly_spaced(self):
        indices = select_keyframe_indices(20, 5)
        assert len(indices) == 5
        assert indices[0] == 0
        assert indices[-1] == 19

    def test_large_over_cap(self):
        indices = select_keyframe_indices(500, 300)
        assert len(indices) == 300
        assert indices[0] == 0
        assert indices[-1] == 499

    def test_max_frames_zero(self):
        assert select_keyframe_indices(10, 0) == []

    def test_max_frames_one(self):
        assert select_keyframe_indices(10, 1) == [0]

    def test_max_frames_two(self):
        assert select_keyframe_indices(10, 2) == [0, 9]

    def test_always_includes_endpoints(self):
        indices = select_keyframe_indices(123, 17)
        assert 0 in indices
        assert 122 in indices

    def test_sorted_output(self):
        indices = select_keyframe_indices(123, 17)
        assert indices == sorted(indices)

    def test_no_duplicates(self):
        indices = select_keyframe_indices(500, 300)
        assert len(indices) == len(set(indices))
