#!/usr/bin/env python3
"""Speech Segments with Speaker Diarization CLI 러너

화자 분리 기능이 포함된 STT 파이프라인

Usage:
    python run_speech_segments_diarization.py --video <path> --out <json>
    
Example:
    python run_speech_segments_diarization.py --video sample.mp4 --out artifacts/result.json
    python run_speech_segments_diarization.py --video sample.mp4 --out result.json --model small --lang ko --num-speakers 2

Requirements:
    - openai-whisper
    - pyannote.audio  
    - HuggingFace token (HF_TOKEN 환경변수)
"""
import argparse
import logging
import os
import sys
from pathlib import Path

# 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from speech_segments.stt_diarization import (
    STTDiarizationProcessor,
    DiarizedSegment,
    convert_to_speech_segments
)


def setup_logging(verbose: bool = False):
    """로깅 설정"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def main():
    parser = argparse.ArgumentParser(
        description="화자 분리 포함 Speech Segments 파이프라인",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 기본 실행 (화자 수 자동 감지)
    python run_speech_segments_diarization.py --video input.mp4 --out result.json
    
    # 화자 수 지정 (2명)
    python run_speech_segments_diarization.py --video input.mp4 --out result.json --num-speakers 2
    
    # 한국어 + small 모델
    python run_speech_segments_diarization.py --video input.mp4 --out result.json --model small --lang ko
    
    # 화자 수 범위 지정
    python run_speech_segments_diarization.py --video input.mp4 --out result.json --min-speakers 2 --max-speakers 5

Note:
    HuggingFace 토큰이 필요합니다. 환경변수로 설정하세요:
    export HF_TOKEN=your_token_here
    
    토큰 발급: https://huggingface.co/settings/tokens
    pyannote 모델 동의: https://huggingface.co/pyannote/speaker-diarization-3.1
        """
    )
    parser.add_argument(
        "--video", "-v",
        required=True,
        help="입력 비디오 파일 경로"
    )
    parser.add_argument(
        "--out", "-o",
        required=True,
        help="출력 JSON 파일 경로"
    )
    parser.add_argument(
        "--model", "-m",
        default="base",
        choices=["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"],
        help="Whisper 모델 (기본: base)"
    )
    parser.add_argument(
        "--lang", "-l",
        default=None,
        help="언어 코드 (예: ko, en, ja). 미지정시 자동 감지"
    )
    parser.add_argument(
        "--num-speakers",
        type=int,
        default=None,
        help="정확한 화자 수 (알고 있는 경우)"
    )
    parser.add_argument(
        "--min-speakers",
        type=int,
        default=None,
        help="최소 화자 수"
    )
    parser.add_argument(
        "--max-speakers",
        type=int,
        default=None,
        help="최대 화자 수"
    )
    parser.add_argument(
        "--hf-token",
        default=None,
        help="HuggingFace 토큰 (또는 HF_TOKEN 환경변수 사용)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="상세 로그 출력"
    )
    parser.add_argument(
        "--format-txt",
        action="store_true",
        help="포맷된 텍스트 파일도 저장 (.txt)"
    )
    
    args = parser.parse_args()
    
    # 로깅 설정
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    # HF 토큰 확인
    hf_token = args.hf_token or os.environ.get("HF_TOKEN")
    if not hf_token:
        print("\nError: HuggingFace 토큰이 필요합니다.")
        print("\n설정 방법:")
        print("  1. https://huggingface.co/settings/tokens 에서 토큰 발급")
        print("  2. https://huggingface.co/pyannote/speaker-diarization-3.1 에서 모델 사용 동의")
        print("  3. 환경변수 설정: export HF_TOKEN=your_token_here")
        print("  또는 --hf-token 옵션 사용")
        sys.exit(1)
    
    # 출력 디렉터리 생성
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # artifacts 디렉터리 설정
    video_path = Path(args.video)
    video_id = video_path.stem
    artifacts_dir = Path("artifacts") / video_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Video: {args.video}")
    logger.info(f"Output: {args.out}")
    logger.info(f"Model: {args.model}")
    logger.info(f"Language: {args.lang or 'auto-detect'}")
    if args.num_speakers:
        logger.info(f"Num speakers: {args.num_speakers}")
    
    # 프로세서 초기화
    processor = STTDiarizationProcessor(
        model_name=args.model,
        language=args.lang,
        hf_token=hf_token,
        num_speakers=args.num_speakers,
        min_speakers=args.min_speakers,
        max_speakers=args.max_speakers,
    )
    
    # 처리 실행
    import time
    start_time = time.time()
    
    segments = processor.process(args.video)
    
    processing_time = time.time() - start_time
    
    if not segments:
        print(f"\nError: 세그먼트를 추출하지 못했습니다.")
        print("\n=== Troubleshooting ===")
        print("1. ffmpeg 확인: ffmpeg -version")
        print("2. whisper 확인: pip install openai-whisper")
        print("3. pyannote 확인: pip install pyannote.audio")
        print("4. HF 토큰 확인: echo $HF_TOKEN")
        print("5. 비디오 파일 확인: ffprobe <video_path>")
        print("========================")
        sys.exit(1)
    
    # JSON 저장
    processor.save_transcript(segments, out_path, video_path=args.video)
    
    # transcript.json도 artifacts에 저장
    transcript_path = artifacts_dir / "transcript_diarized.json"
    processor.save_transcript(segments, transcript_path, video_path=args.video)
    
    # 포맷된 텍스트 저장 (옵션)
    if args.format_txt:
        txt_path = out_path.with_suffix('.txt')
        formatted = processor.format_transcript(segments)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(formatted)
        logger.info(f"Formatted transcript saved to {txt_path}")
    
    # 결과 출력
    speakers = set(seg.speaker for seg in segments)
    total_duration = max(seg.end_s for seg in segments) if segments else 0.0
    
    print(f"\nSuccess!")
    print(f"Segments: {len(segments)}")
    print(f"Speakers: {len(speakers)} ({', '.join(sorted(speakers))})")
    print(f"Duration: {total_duration:.1f}s")
    print(f"Processing time: {processing_time:.1f}s")
    print(f"Output: {args.out}")
    print(f"Transcript: {transcript_path}")
    
    # 화자별 통계
    print(f"\n   Speaker stats:")
    for speaker in sorted(speakers):
        speaker_segs = [s for s in segments if s.speaker == speaker]
        speaker_duration = sum(s.end_s - s.start_s for s in speaker_segs)
        print(f"     {speaker}: {len(speaker_segs)} segments, {speaker_duration:.1f}s")
    
    # 미리보기
    if args.verbose and segments:
        print(f"\n   Preview (first 5 segments):")
        for seg in segments[:5]:
            text_preview = seg.text[:40] + "..." if len(seg.text) > 40 else seg.text
            print(f"     [{seg.start_s:.1f}s - {seg.end_s:.1f}s] {seg.speaker}: {text_preview}")


if __name__ == "__main__":
    main()