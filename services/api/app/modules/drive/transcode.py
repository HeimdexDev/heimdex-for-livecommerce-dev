import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ProbeResult:
    width: int
    height: int
    codec_name: str
    bitrate_kbps: int
    duration_ms: int
    has_audio: bool
    audio_codec: Optional[str] = None
    audio_bitrate_kbps: Optional[int] = None


@dataclass
class TranscodeDecision:
    should_transcode: bool
    reason: str
    should_cap_bitrate: bool = False


def probe_video(path: Path) -> ProbeResult:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), None
    )
    audio_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None
    )

    if not video_stream:
        raise ValueError(f"No video stream found in {path}")

    fmt = data.get("format", {})
    total_bitrate = int(fmt.get("bit_rate", 0)) // 1000
    duration_s = float(fmt.get("duration", 0))

    video_bitrate = int(video_stream.get("bit_rate", 0)) // 1000
    if video_bitrate == 0:
        video_bitrate = total_bitrate - (int(audio_stream.get("bit_rate", 0)) // 1000 if audio_stream else 0)
        video_bitrate = max(video_bitrate, 0)

    return ProbeResult(
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        codec_name=video_stream.get("codec_name", "unknown"),
        bitrate_kbps=video_bitrate,
        duration_ms=int(duration_s * 1000),
        has_audio=audio_stream is not None,
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
        audio_bitrate_kbps=int(audio_stream.get("bit_rate", 0)) // 1000 if audio_stream else None,
    )


def make_transcode_decision(probe: ProbeResult) -> TranscodeDecision:
    """
    Decide whether to transcode based on spike findings:
    - 720p H.264 can INCREASE in size after re-encode (1718→1985 kbps observed).
    - Always enforce maxrate/bufsize when transcoding.
    - Skip transcode if already <=720p, H.264, and bitrate <= target max.
    """
    settings = get_settings()
    max_height = settings.drive_proxy_max_height
    max_bitrate_kbps = int(settings.drive_proxy_max_bitrate.rstrip("k"))

    is_h264 = probe.codec_name in ("h264", "h264_qsv", "h264_nvenc")
    is_within_resolution = probe.height <= max_height
    is_within_bitrate = probe.bitrate_kbps <= max_bitrate_kbps

    if is_h264 and is_within_resolution and is_within_bitrate:
        return TranscodeDecision(
            should_transcode=False,
            reason=f"Already H.264 {probe.width}x{probe.height} @ {probe.bitrate_kbps}kbps (within {max_bitrate_kbps}kbps cap)",
        )

    if is_h264 and is_within_resolution and not is_within_bitrate:
        return TranscodeDecision(
            should_transcode=True,
            should_cap_bitrate=True,
            reason=f"H.264 {probe.width}x{probe.height} but bitrate {probe.bitrate_kbps}kbps exceeds {max_bitrate_kbps}kbps cap",
        )

    reasons = []
    if not is_h264:
        reasons.append(f"codec={probe.codec_name}")
    if not is_within_resolution:
        reasons.append(f"height={probe.height} > {max_height}")
    if not is_within_bitrate:
        reasons.append(f"bitrate={probe.bitrate_kbps}kbps > {max_bitrate_kbps}kbps")

    return TranscodeDecision(
        should_transcode=True,
        reason=f"Requires transcode: {', '.join(reasons)}",
    )


def transcode_to_proxy(
    input_path: Path,
    output_path: Path,
    probe: ProbeResult,
    decision: TranscodeDecision,
) -> Path:
    settings = get_settings()

    cmd = ["ffmpeg", "-y", "-i", str(input_path)]

    if decision.should_cap_bitrate and probe.height <= settings.drive_proxy_max_height:
        # Already correct resolution — only cap bitrate via stream copy is not possible,
        # so re-encode with strict bitrate limits.
        cmd.extend([
            "-c:v", "libx264",
            "-preset", settings.drive_proxy_preset,
            "-maxrate", settings.drive_proxy_max_bitrate,
            "-bufsize", settings.drive_proxy_bufsize,
            "-crf", str(settings.drive_proxy_crf),
        ])
    else:
        cmd.extend([
            "-c:v", "libx264",
            "-preset", settings.drive_proxy_preset,
            "-crf", str(settings.drive_proxy_crf),
            "-maxrate", settings.drive_proxy_max_bitrate,
            "-bufsize", settings.drive_proxy_bufsize,
            "-vf", f"scale=-2:{settings.drive_proxy_max_height}",
        ])

    if probe.has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", settings.drive_proxy_audio_bitrate])
    else:
        cmd.extend(["-an"])

    cmd.extend(["-movflags", "+faststart", str(output_path)])

    logger.info(
        "transcode_started",
        extra={
            "input": str(input_path),
            "output": str(output_path),
            "decision": decision.reason,
            "probe": {
                "width": probe.width,
                "height": probe.height,
                "codec": probe.codec_name,
                "bitrate_kbps": probe.bitrate_kbps,
            },
        },
    )

    subprocess.run(cmd, check=True, capture_output=True, text=True)

    output_size = output_path.stat().st_size
    input_size = input_path.stat().st_size
    logger.info(
        "transcode_complete",
        extra={
            "input_size": input_size,
            "output_size": output_size,
            "size_ratio": round(output_size / input_size, 3) if input_size > 0 else 0,
        },
    )

    return output_path
