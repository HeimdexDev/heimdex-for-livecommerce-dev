#!/usr/bin/env python3
"""Speech Segments 파이프라인 CLI 러너

Usage:
    python run_speech_segments.py --video <path> --out <json>
    
Example:
    python run_speech_segments.py --video sample.mp4 --out artifacts/result.json
    python run_speech_segments.py --video sample.mp4 --out result.json --model small --lang ko
"""
import argparse
import logging
import sys
from pathlib import Path

# 모듈 경로 추가 (scripts/가 speech_segments/ 안에 있는 경우)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from speech_segments import SpeechSegmentsPipeline, PipelineResult


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
        description="Speech Segments 파이프라인 실행",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 기본 실행
    python run_speech_segments.py --video input.mp4 --out result.json
    
    # artifacts 폴더에 저장 (transcript.json도 생성됨)
    python run_speech_segments.py --video input.mp4 --out artifacts/result.json
    
    # 한국어 + small 모델 사용
    python run_speech_segments.py --video input.mp4 --out result.json --model small --lang ko
    
    # 영어 + large 모델 (정확도 높음, 느림)
    python run_speech_segments.py --video input.mp4 --out result.json --model large --lang en
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
        help="Whisper 모델 (기본: base). tiny=가장 빠름, large=가장 정확"
    )
    parser.add_argument(
        "--lang", "-l",
        default=None,
        help="언어 코드 (예: ko, en, ja). 지정하지 않으면 자동 감지"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="상세 로그 출력"
    )
    parser.add_argument(
        "--no-transcript",
        action="store_true",
        help="transcript.json 파일 생성 안 함"
    )
    
    args = parser.parse_args()
    
    # 로깅 설정
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    # 출력 디렉터리 생성
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # artifacts 디렉터리 설정
    video_path = Path(args.video)
    video_id = video_path.stem
    artifacts_dir = Path("artifacts") / video_id
    
    logger.info(f"Video: {args.video}")
    logger.info(f"Output: {args.out}")
    logger.info(f"Model: {args.model}")
    logger.info(f"Language: {args.lang or 'auto-detect'}")
    
    # 파이프라인 실행
    pipeline = SpeechSegmentsPipeline(
        whisper_model=args.model,
        language=args.lang
    )
    
    result = pipeline.run(
        args.video,
        save_transcript=not args.no_transcript,
        artifacts_dir=str(artifacts_dir)
    )
    
    # 결과 저장
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result.to_json())
    
    # 결과 출력
    if result.status == "success":
        print(f"\nSuccess: {len(result.segments)} segments found")
        print(f"   Total duration: {result.total_duration:.1f}s")
        print(f"   Processing time: {result.processing_time:.1f}s")
        print(f"   Output saved to: {args.out}")
        
        if not args.no_transcript:
            transcript_path = artifacts_dir / "transcript.json"
            print(f"   Transcript saved to: {transcript_path}")
        
        # 처음 3개 세그먼트 미리보기
        if result.segments and args.verbose:
            print("\n   Preview (first 3 segments):")
            for i, seg in enumerate(result.segments[:3]):
                print(f"   [{seg.start:.1f}s - {seg.end:.1f}s] {seg.text[:50]}...")
    else:
        print(f"\nError: {result.error}")
        print("\n=== Troubleshooting ===")
        print("1. Check ffmpeg: ffmpeg -version")
        print("2. Check whisper: pip install openai-whisper")
        print("3. Check video: ffprobe <video_path>")
        print("4. Try smaller model: --model tiny")
        print("========================")
        sys.exit(1)


if __name__ == "__main__":
    main()