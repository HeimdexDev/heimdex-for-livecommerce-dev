"""STT (Speech-to-Text) 모듈

비디오에서 오디오를 추출하고 Whisper를 사용하여 텍스트로 변환
출력: [{start_s, end_s, text}] (문장 단위)

lawfirm 프로겍트 참고
- ffmpeg.py: extract_audio()
- advanced_audio_processor.py의 extract_audio
"""
import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TranscriptSegment:
    """STT 결과 세그먼트 (문장 단위)"""
    start_s: float
    end_s: float
    text: str
    
    def to_dict(self) -> dict:
        return asdict(self)


class STTProcessor:
    """Whisper 기반 음성-텍스트 변환 프로세서"""
    
    # 지원하는 Whisper 모델
    SUPPORTED_MODELS = ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]
    
    def __init__(
        self,
        model_name: str = "base",
        language: Optional[str] = None,
        device: str = "auto"
    ):
        """
        Args:
            model_name: Whisper 모델 이름 (tiny, base, small, medium, large)
            language: 언어 코드 (예: "ko", "en"). None이면 자동 감지
            device: 디바이스 ("auto", "cpu", "cuda")
        """
        self.model_name = model_name
        self.language = language
        self.device = device
        self._model = None
        
        if model_name not in self.SUPPORTED_MODELS:
            logger.warning(f"Unknown model '{model_name}', using 'base'")
            self.model_name = "base"
    
    def _load_model(self):
        """Whisper 모델 로드 (지연 로딩)"""
        if self._model is not None:
            return
        
        try:
            import whisper
            logger.info(f"Loading Whisper model: {self.model_name}")
            
            device = self.device
            if device == "auto":
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            
            self._model = whisper.load_model(self.model_name, device=device)
            logger.info(f"Whisper model loaded on {device}")
            
        except ImportError as e:
            logger.error(f"Failed to import whisper: {e}")
            logger.error("Install with: pip install openai-whisper")
            raise
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise
    
    def extract_audio(self, video_path: Path, output_path: Path) -> Path:
        """비디오에서 오디오 추출 (16kHz mono WAV)
        
        Args:
            video_path: 입력 비디오 경로
            output_path: 출력 오디오 경로
            
        Returns:
            추출된 오디오 파일 경로
            
        Raises:
            subprocess.CalledProcessError: ffmpeg 실패 시
            FileNotFoundError: 비디오 파일이 없을 때
        """
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        logger.info(f"Extracting audio from {video_path}")
        
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vn",  # 비디오 제외
            "-acodec", "pcm_s16le",  # 16-bit PCM
            "-ar", "16000",  # 16kHz (Whisper 최적화)
            "-ac", "1",  # 모노
            "-y",  # 덮어쓰기
            str(output_path),
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            logger.debug(f"ffmpeg output: {result.stderr}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Audio extraction failed: {e.stderr}")
            raise
        
        if not output_path.exists():
            raise FileNotFoundError(f"Audio extraction failed: {output_path} not created")
        
        file_size = output_path.stat().st_size
        logger.info(f"Audio extracted: {output_path} ({file_size / 1024:.1f} KB)")
        
        return output_path
    
    def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        """오디오 파일을 텍스트로 변환
        
        Args:
            audio_path: 오디오 파일 경로
            
        Returns:
            TranscriptSegment 리스트 (문장 단위, 타임스탬프 포함)
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        self._load_model()
        
        logger.info(f"Transcribing audio: {audio_path}")
        
        try:
            # Whisper 옵션
            options = {
                "task": "transcribe",
                "verbose": False,
            }
            
            if self.language:
                options["language"] = self.language
            
            # Whisper 실행
            result = self._model.transcribe(str(audio_path), **options)
            
            # 세그먼트 추출
            segments = []
            for seg in result.get("segments", []):
                transcript_seg = TranscriptSegment(
                    start_s=round(seg["start"], 3),
                    end_s=round(seg["end"], 3),
                    text=seg["text"].strip()
                )
                if transcript_seg.text:  # 빈 텍스트 제외
                    segments.append(transcript_seg)
            
            logger.info(f"Transcription complete: {len(segments)} segments")
            
            # 감지된 언어 로깅
            detected_lang = result.get("language", "unknown")
            logger.info(f"Detected language: {detected_lang}")
            
            return segments
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise
    
    def process(self, video_path: str | Path) -> list[TranscriptSegment]:
        """비디오 파일에서 STT 전체 파이프라인 실행
        
        Args:
            video_path: 비디오 파일 경로
            
        Returns:
            TranscriptSegment 리스트
        """
        video_path = Path(video_path)
        
        if not video_path.exists():
            logger.error(f"Video file not found: {video_path}")
            return []
        
        # 임시 디렉터리에서 오디오 추출 및 처리
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_path = temp_path / "audio.wav"
            
            try:
                # Step 1: 오디오 추출
                self.extract_audio(video_path, audio_path)
                
                # Step 2: 트랜스크립션
                segments = self.transcribe(audio_path)
                
                return segments
                
            except FileNotFoundError as e:
                logger.error(f"File not found: {e}")
                return []
            except subprocess.CalledProcessError as e:
                logger.error(f"FFmpeg error: {e}")
                logger.error("Make sure ffmpeg is installed and accessible")
                return []
            except Exception as e:
                logger.error(f"STT processing failed: {e}")
                return []
    
    @staticmethod
    def save_transcript(
        segments: list[TranscriptSegment],
        output_path: Path,
        video_path: Optional[str] = None
    ) -> None:
        """트랜스크립트를 JSON 파일로 저장
        
        Args:
            segments: TranscriptSegment 리스트
            output_path: 출력 JSON 파일 경로
            video_path: 원본 비디오 경로 (메타데이터용)
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "video_path": str(video_path) if video_path else None,
            "segments": [seg.to_dict() for seg in segments],
            "total_segments": len(segments),
        }
        
        # 총 duration 계산
        if segments:
            data["total_duration_s"] = max(seg.end_s for seg in segments)
        else:
            data["total_duration_s"] = 0.0
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Transcript saved to {output_path}")


# schemas.py와의 호환을 위한 변환 함수
def convert_to_speech_segments(transcript_segments: list[TranscriptSegment]):
    """TranscriptSegment를 SpeechSegment로 변환
    
    Args:
        transcript_segments: STT 결과 세그먼트 리스트
        
    Returns:
        SpeechSegment 리스트
    """
    from .schemas import SpeechSegment
    
    return [
        SpeechSegment(
            start=seg.start_s,
            end=seg.end_s,
            text=seg.text,
            confidence=1.0  # Whisper는 기본적으로 신뢰도를 제공하지 않음
        )
        for seg in transcript_segments
    ]