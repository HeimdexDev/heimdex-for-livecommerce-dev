from typing import NotRequired, TypedDict


class EdlClip(TypedDict):
    clip_name: str
    media_path: str
    start_ms: int
    end_ms: int
    source_path: NotRequired[str]


def ms_to_timecode(ms: int, fps: int) -> str:
    total_frames = round(ms * fps / 1000.0)
    frames = total_frames % fps
    total_seconds = total_frames // fps
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def generate_edl(
    clips: list[EdlClip],
    title: str,
    frame_rate: float,
) -> str:
    fps = round(frame_rate)
    if fps <= 0:
        fps = 30

    is_drop_frame = abs(frame_rate - 29.97) < 0.01 or abs(frame_rate - 59.94) < 0.01

    lines = [f"TITLE: {title}"]
    lines.append("FCM: DROP FRAME" if is_drop_frame else "FCM: NON-DROP FRAME")
    lines.append("")

    record_offset_ms = 0
    for i, clip in enumerate(clips, start=1):
        src_in = ms_to_timecode(clip["start_ms"], fps)
        src_out = ms_to_timecode(clip["end_ms"], fps)
        rec_in = ms_to_timecode(record_offset_ms, fps)
        duration_ms = clip["end_ms"] - clip["start_ms"]
        rec_out = ms_to_timecode(record_offset_ms + duration_ms, fps)

        lines.append(f"{i:03d}  {'AX':<8s} {'V':<5s} C        {src_in} {src_out} {rec_in} {rec_out}")
        lines.append(f"* FROM CLIP NAME:  {clip['clip_name']}")
        lines.append(f"* MEDIA PATH:  {clip['media_path']}")

        source_path = clip.get("source_path")
        if source_path:
            lines.append(f"* SOURCE:  {source_path}")

        record_offset_ms += duration_ms

    lines.append("")
    return "\n".join(lines)
