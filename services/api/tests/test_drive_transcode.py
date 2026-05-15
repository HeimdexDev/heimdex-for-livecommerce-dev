import pytest

transcoding = pytest.importorskip(
    "heimdex_media_pipelines.transcoding",
    reason="cross-package contract test requires heimdex-media-pipelines",
)

pytestmark = pytest.mark.contract

ProbeResult = transcoding.ProbeResult
TranscodeDecision = transcoding.TranscodeDecision
make_transcode_decision = transcoding.make_transcode_decision


def _make_probe(
    width: int = 1280,
    height: int = 720,
    codec_name: str = "h264",
    bitrate_kbps: int = 1500,
    duration_ms: int = 60000,
    has_audio: bool = True,
) -> ProbeResult:
    return ProbeResult(
        width=width,
        height=height,
        codec_name=codec_name,
        bitrate_kbps=bitrate_kbps,
        duration_ms=duration_ms,
        has_audio=has_audio,
    )


class TestTranscodeDecision:
    def test_skip_h264_720p_within_bitrate(self):
        probe = _make_probe(height=720, codec_name="h264", bitrate_kbps=1500)
        decision = make_transcode_decision(probe)
        assert decision.should_transcode is False
        assert "Already H.264" in decision.reason

    def test_skip_h264_lower_than_720p(self):
        probe = _make_probe(height=480, codec_name="h264", bitrate_kbps=800)
        decision = make_transcode_decision(probe)
        assert decision.should_transcode is False

    def test_transcode_h264_720p_high_bitrate(self):
        probe = _make_probe(height=720, codec_name="h264", bitrate_kbps=3000)
        decision = make_transcode_decision(probe)
        assert decision.should_transcode is True
        assert decision.should_cap_bitrate is True
        assert "exceeds" in decision.reason

    def test_transcode_non_h264_codec(self):
        probe = _make_probe(height=720, codec_name="hevc", bitrate_kbps=1500)
        decision = make_transcode_decision(probe)
        assert decision.should_transcode is True
        assert "codec=hevc" in decision.reason

    def test_transcode_high_resolution(self):
        probe = _make_probe(height=1080, codec_name="h264", bitrate_kbps=1500)
        decision = make_transcode_decision(probe)
        assert decision.should_transcode is True
        assert "height=1080" in decision.reason

    def test_transcode_4k_hevc_high_bitrate(self):
        probe = _make_probe(height=2160, codec_name="hevc", bitrate_kbps=15000)
        decision = make_transcode_decision(probe)
        assert decision.should_transcode is True
        assert "codec=hevc" in decision.reason
        assert "height=2160" in decision.reason

    def test_spike_case_720p_h264_1718kbps_should_skip(self):
        """Spike finding: 720p H.264 @ 1718kbps is within 2500k cap, should SKIP."""
        probe = _make_probe(height=720, codec_name="h264", bitrate_kbps=1718)
        decision = make_transcode_decision(probe)
        assert decision.should_transcode is False

    def test_spike_case_reencoded_1985kbps_should_skip(self):
        """Spike finding: after re-encode bitrate rose to 1985kbps but still within cap."""
        probe = _make_probe(height=720, codec_name="h264", bitrate_kbps=1985)
        decision = make_transcode_decision(probe)
        assert decision.should_transcode is False

    def test_h264_at_exact_cap_should_skip(self):
        probe = _make_probe(height=720, codec_name="h264", bitrate_kbps=2500)
        decision = make_transcode_decision(probe)
        assert decision.should_transcode is False

    def test_h264_just_over_cap_should_transcode(self):
        probe = _make_probe(height=720, codec_name="h264", bitrate_kbps=2501)
        decision = make_transcode_decision(probe)
        assert decision.should_transcode is True
        assert decision.should_cap_bitrate is True

    def test_vp9_codec_triggers_transcode(self):
        probe = _make_probe(height=720, codec_name="vp9", bitrate_kbps=1500)
        decision = make_transcode_decision(probe)
        assert decision.should_transcode is True

    def test_360p_h264_low_bitrate_skips(self):
        probe = _make_probe(width=640, height=360, codec_name="h264", bitrate_kbps=500)
        decision = make_transcode_decision(probe)
        assert decision.should_transcode is False
