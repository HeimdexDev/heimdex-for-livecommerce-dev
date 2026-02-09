"""STT with Speaker Diarization 모듈

비디오에서 오디오를 추출하고 Whisper + pyannote로 화자 분리된 텍스트 변환
출력: [{start_s, end_s, text, speaker}] (화자별 문장 단위)

lawfirm 프로겍트 참고
- ffmpeg.py: extract_audio() - ffmpeg 
- advanced_audio_processor.py: _transcribe_segments() - 화자 분리 포맷
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
class DiarizedSegment:
    """화자 분리된 STT 결과 세그먼트"""
    start_s: float
    end_s: float
    text: str
    speaker: str  # "SPEAKER_00", "SPEAKER_01", ...
    
    def to_dict(self) -> dict:
        return asdict(self)


class STTDiarizationProcessor:
    """Whisper + pyannote 기반 화자 분리 STT 프로세서
    
    Requirements:
        - openai-whisper
        - pyannote.audio
        - torch
        - HuggingFace token (pyannote 모델 다운로드용)
    """
    
    SUPPORTED_MODELS = ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]
    
    def __init__(
        self,
        model_name: str = "base",
        language: Optional[str] = None,
        device: str = "auto",
        hf_token: Optional[str] = None,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ):
        """
        Args:
            model_name: Whisper 모델 이름
            language: 언어 코드 (예: "ko", "en")
            device: 디바이스 ("auto", "cpu", "cuda")
            hf_token: HuggingFace 토큰 (pyannote 모델용)
            num_speakers: 정확한 화자 수 (알고 있는 경우)
            min_speakers: 최소 화자 수
            max_speakers: 최대 화자 수
        """
        self.model_name = model_name
        self.language = language
        self.device = device
        self.hf_token = hf_token
        self.num_speakers = num_speakers
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers
        
        self._whisper_model = None
        self._diarization_pipeline = None
        
        if model_name not in self.SUPPORTED_MODELS:
            logger.warning(f"Unknown model '{model_name}', using 'base'")
            self.model_name = "base"
    
    def _get_device(self) -> str:
        """디바이스 결정"""
        if self.device != "auto":
            return self.device
        
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    
    def _load_whisper(self):
        """Whisper 모델 로드"""
        if self._whisper_model is not None:
            return
        
        try:
            import whisper
            device = self._get_device()
            logger.info(f"Loading Whisper model: {self.model_name} on {device}")
            self._whisper_model = whisper.load_model(self.model_name, device=device)
            logger.info("Whisper model loaded")
        except ImportError:
            logger.error("whisper not installed. Run: pip install openai-whisper")
            raise
    
    def _load_diarization(self):
        """pyannote 화자 분리 파이프라인 로드"""
        if self._diarization_pipeline is not None:
            return
        
        try:
            from pyannote.audio import Pipeline
            import os
            
            logger.info("Loading pyannote diarization pipeline...")
            
            # HuggingFace 토큰 설정
            if not self.hf_token:
                self.hf_token = os.environ.get("HF_TOKEN")
            
            if not self.hf_token:
                raise ValueError(
                    "HuggingFace token required for pyannote. "
                    "Set HF_TOKEN environment variable or pass hf_token parameter. "
                    "Get token at: https://huggingface.co/settings/tokens"
                )
            
            # 환경변수로 토큰 설정 (pyannote가 자동으로 읽음)
            os.environ["HF_TOKEN"] = self.hf_token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = self.hf_token
            
            self._diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1"
            )
            
            # GPU 사용 설정
            device = self._get_device()
            if device == "cuda":
                import torch
                self._diarization_pipeline.to(torch.device("cuda"))
            
            logger.info("Diarization pipeline loaded")
            
        except ImportError:
            logger.error("pyannote.audio not installed. Run: pip install pyannote.audio")
            raise
    
    def extract_audio(self, video_path: Path, output_path: Path) -> Path:
        """비디오에서 오디오 추출 (16kHz mono WAV)"""
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        logger.info(f"Extracting audio from {video_path}")
        
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-y",
            str(output_path),
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Audio extraction failed: {e.stderr}")
            raise
        
        if not output_path.exists():
            raise FileNotFoundError(f"Audio extraction failed: {output_path}")
        
        logger.info(f"Audio extracted: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")
        return output_path
    
    def run_diarization(self, audio_path: Path) -> list[tuple[float, float, str]]:
        """화자 분리 실행
        
        Returns:
            [(start_s, end_s, speaker), ...] 리스트
        """
        self._load_diarization()
        
        logger.info(f"Running speaker diarization on {audio_path}")
        
        # 화자 수 힌트 설정
        diarization_params = {}
        if self.num_speakers:
            diarization_params["num_speakers"] = self.num_speakers
        if self.min_speakers:
            diarization_params["min_speakers"] = self.min_speakers
        if self.max_speakers:
            diarization_params["max_speakers"] = self.max_speakers
        
        # 화자 분리 실행
        diarization = self._diarization_pipeline(
            str(audio_path),
            **diarization_params
        )
        
        # 결과 추출
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append((turn.start, turn.end, speaker))
        
        logger.info(f"Diarization complete: {len(segments)} segments, "
                   f"{len(set(s[2] for s in segments))} speakers")
        
        return segments
    
    def transcribe_with_diarization(self, audio_path: Path) -> list[DiarizedSegment]:
        """화자 분리 + STT 실행
        
        Returns:
            DiarizedSegment 리스트
        """
        self._load_whisper()
        
        # 1. 화자 분리
        speaker_segments = self.run_diarization(audio_path)
        
        # 2. Whisper로 전체 오디오 트랜스크립션
        logger.info("Running Whisper transcription...")
        
        options = {"task": "transcribe", "verbose": False}
        if self.language:
            options["language"] = self.language
        
        whisper_result = self._whisper_model.transcribe(str(audio_path), **options)
        whisper_segments = whisper_result.get("segments", [])
        
        logger.info(f"Whisper complete: {len(whisper_segments)} segments")
        
        # 3. 화자 분리 결과와 Whisper 결과 매칭
        diarized_segments = self._align_segments(speaker_segments, whisper_segments)
        
        logger.info(f"Alignment complete: {len(diarized_segments)} diarized segments")
        
        return diarized_segments
    
    def _align_segments(
        self,
        speaker_segments: list[tuple[float, float, str]],
        whisper_segments: list[dict]
    ) -> list[DiarizedSegment]:
        """화자 분리 결과와 Whisper 결과를 정렬/매칭
        
        각 Whisper 세그먼트에 대해 가장 많이 겹치는 화자를 할당
        """
        results = []
        
        for wseg in whisper_segments:
            w_start = wseg["start"]
            w_end = wseg["end"]
            w_text = wseg["text"].strip()
            
            if not w_text:
                continue
            
            # 가장 많이 겹치는 화자 찾기
            best_speaker = "SPEAKER_UNKNOWN"
            best_overlap = 0.0
            
            for s_start, s_end, speaker in speaker_segments:
                # 겹치는 구간 계산
                overlap_start = max(w_start, s_start)
                overlap_end = min(w_end, s_end)
                overlap = max(0, overlap_end - overlap_start)
                
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = speaker
            
            results.append(DiarizedSegment(
                start_s=round(w_start, 3),
                end_s=round(w_end, 3),
                text=w_text,
                speaker=best_speaker
            ))
        
        return results
    
    def process(self, video_path: str | Path) -> list[DiarizedSegment]:
        """전체 파이프라인 실행
        
        Args:
            video_path: 비디오 파일 경로
            
        Returns:
            DiarizedSegment 리스트
        """
        video_path = Path(video_path)
        
        if not video_path.exists():
            logger.error(f"Video file not found: {video_path}")
            return []
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_path = temp_path / "audio.wav"
            
            try:
                # Step 1: 오디오 추출
                self.extract_audio(video_path, audio_path)
                
                # Step 2: 화자 분리 + 트랜스크립션
                segments = self.transcribe_with_diarization(audio_path)
                
                return segments
                
            except Exception as e:
                logger.error(f"Processing failed: {e}", exc_info=True)
                return []
    
    @staticmethod
    def save_transcript(
        segments: list[DiarizedSegment],
        output_path: Path,
        video_path: Optional[str] = None
    ) -> None:
        """트랜스크립트를 JSON 파일로 저장"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 화자별 통계
        speakers = set(seg.speaker for seg in segments)
        speaker_stats = {}
        for speaker in speakers:
            speaker_segs = [s for s in segments if s.speaker == speaker]
            speaker_stats[speaker] = {
                "segment_count": len(speaker_segs),
                "total_duration_s": sum(s.end_s - s.start_s for s in speaker_segs)
            }
        
        data = {
            "video_path": str(video_path) if video_path else None,
            "segments": [seg.to_dict() for seg in segments],
            "total_segments": len(segments),
            "total_duration_s": max(seg.end_s for seg in segments) if segments else 0.0,
            "num_speakers": len(speakers),
            "speaker_stats": speaker_stats
        }
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Transcript saved to {output_path}")
    
    @staticmethod
    def format_transcript(segments: list[DiarizedSegment]) -> str:
        """포맷된 트랜스크립트 문자열 생성
        
        Format: [HH:MM:SS.S - HH:MM:SS.S] SPEAKER: text
        """
        lines = []
        for seg in segments:
            start_ts = _format_timestamp(seg.start_s)
            end_ts = _format_timestamp(seg.end_s)
            lines.append(f"[{start_ts} - {end_ts}] {seg.speaker}: {seg.text}")
        return "\n".join(lines)


def _format_timestamp(seconds: float) -> str:
    """초를 HH:MM:SS.S 형식으로 변환"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:04.1f}"


# schemas.py와의 호환을 위한 변환 함수
def convert_to_speech_segments(diarized_segments: list[DiarizedSegment]):
    """DiarizedSegment를 SpeechSegment로 변환"""
    from .schemas import SpeechSegment
    
    return [
        SpeechSegment(
            start=seg.start_s,
            end=seg.end_s,
            text=f"[{seg.speaker}] {seg.text}",
            confidence=1.0
        )
        for seg in diarized_segments
    ]