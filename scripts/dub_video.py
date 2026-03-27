import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.logger import get_logger
from src.utils.video_dubbing import dub_video

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Chinese dubbing for a local video + SRT")
    parser.add_argument("--video", required=True, help="Input video path")
    parser.add_argument("--srt", required=True, help="Translated Chinese SRT path")
    parser.add_argument("--output", required=True, help="Output dubbed video path")
    parser.add_argument("--work-dir", default="", help="Optional work dir for intermediate files")
    parser.add_argument("--bg-volume", type=float, default=0.6, help="Background music volume")
    parser.add_argument(
        "--tts-provider",
        choices=["fish", "google", "s2cpp", "auto"],
        default="",
        help="Override VIDEO_DUB_TTS_PROVIDER",
    )
    parser.add_argument("--fish-url", default="", help="Override FISH_TTS_BASE_URL")
    parser.add_argument("--fish-reference-id", default="", help="Reuse existing fish reference_id")
    parser.add_argument("--s2cpp-url", default="", help="Override S2CPP_TTS_BASE_URL")
    parser.add_argument("--s2cpp-reference-audio", default="", help="Override S2CPP_TTS_REFERENCE_AUDIO_PATH")
    parser.add_argument("--s2cpp-reference-text-file", default="", help="Override S2CPP_TTS_REFERENCE_TEXT_FILE")
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    video_path = Path(args.video).resolve()
    srt_path = Path(args.srt).resolve()
    output_path = Path(args.output).resolve()
    work_dir = Path(args.work_dir).resolve() if args.work_dir else None

    if not video_path.exists():
        raise FileNotFoundError(f"视频不存在: {video_path}")
    if not srt_path.exists():
        raise FileNotFoundError(f"SRT 不存在: {srt_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if work_dir is not None:
        work_dir.mkdir(parents=True, exist_ok=True)

    if args.tts_provider:
        os.environ["VIDEO_DUB_TTS_PROVIDER"] = args.tts_provider
    if args.fish_url:
        os.environ["FISH_TTS_BASE_URL"] = args.fish_url
    if args.fish_reference_id:
        os.environ["FISH_TTS_REFERENCE_ID"] = args.fish_reference_id
    if args.s2cpp_url:
        os.environ["S2CPP_TTS_BASE_URL"] = args.s2cpp_url
    if args.s2cpp_reference_audio:
        os.environ["S2CPP_TTS_REFERENCE_AUDIO_PATH"] = args.s2cpp_reference_audio
    if args.s2cpp_reference_text_file:
        os.environ["S2CPP_TTS_REFERENCE_TEXT_FILE"] = args.s2cpp_reference_text_file

    result = await dub_video(
        video_path=video_path,
        srt_path=srt_path,
        output_path=output_path,
        work_dir=work_dir,
        bg_volume=args.bg_volume,
    )
    logger.info(f"Dubbed video saved: {result}")


if __name__ == "__main__":
    asyncio.run(_main())
