"""Tests for EDL generation, ported from Go agent tests."""

from app.modules.export.edl import generate_edl, ms_to_timecode


class TestMsToTimecode:
    def test_zero(self):
        assert ms_to_timecode(0, 30) == "00:00:00:00"

    def test_one_second(self):
        assert ms_to_timecode(1000, 30) == "00:00:01:00"

    def test_fractional_second(self):
        assert ms_to_timecode(500, 30) == "00:00:00:15"

    def test_one_minute(self):
        assert ms_to_timecode(60000, 30) == "00:01:00:00"

    def test_one_hour(self):
        assert ms_to_timecode(3600000, 30) == "01:00:00:00"


class TestGenerateEdl:
    def test_single_clip(self):
        clips = [
            {
                "clip_name": "Intro",
                "media_path": "/media/intro.mp4",
                "start_ms": 0,
                "end_ms": 2000,
            }
        ]
        edl = generate_edl(clips, "Project One", 30.0)

        assert "TITLE: Project One" in edl
        assert "FCM: NON-DROP FRAME" in edl
        assert "001  AX       V     C        00:00:00:00 00:00:02:00 00:00:00:00 00:00:02:00" in edl
        assert "* FROM CLIP NAME:  Intro" in edl
        assert "* MEDIA PATH:  /media/intro.mp4" in edl

    def test_multiple_clips(self):
        clips = [
            {"clip_name": "Clip A", "media_path": "/a.mp4", "start_ms": 0, "end_ms": 1000},
            {"clip_name": "Clip B", "media_path": "/b.mp4", "start_ms": 1000, "end_ms": 2500},
        ]
        edl = generate_edl(clips, "Multi", 30.0)

        assert "001  AX       V     C        00:00:00:00 00:00:01:00 00:00:00:00 00:00:01:00" in edl
        assert "002  AX       V     C        00:00:01:00 00:00:02:15 00:00:01:00 00:00:02:15" in edl

    def test_drop_frame(self):
        clips = [{"clip_name": "Clip", "media_path": "/x.mp4", "start_ms": 0, "end_ms": 1000}]
        edl = generate_edl(clips, "Drop", 29.97)

        assert "FCM: DROP FRAME" in edl

    def test_source_path_comment(self):
        clips = [
            {
                "clip_name": "Interview",
                "media_path": "interview.mp4",
                "start_ms": 0,
                "end_ms": 5000,
                "source_path": "Heimdex Shared Drive/Meetings/interview.mp4",
            }
        ]
        edl = generate_edl(clips, "Cloud Test", 30.0)

        assert "* SOURCE:  Heimdex Shared Drive/Meetings/interview.mp4" in edl

    def test_no_source_path_comment_when_absent(self):
        clips = [
            {
                "clip_name": "Local",
                "media_path": "/local/file.mp4",
                "start_ms": 0,
                "end_ms": 1000,
            }
        ]
        edl = generate_edl(clips, "Local Test", 30.0)

        assert "* SOURCE:" not in edl
