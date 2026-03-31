"""Compare s2cpp vs IndexTTS-2: generate first 20 segments one-by-one, then concatenate."""

import asyncio
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SRT_PATH = PROJECT_ROOT / "posts/video-posts/20260331-002427-一人食晚餐食谱/How To Cook If You're Single • Tasty_subtitled_tts.srt"
OUTPUT_DIR = PROJECT_ROOT / "posts/video-posts/20260331-002427-一人食晚餐食谱/tts_compare"
VIDEO_PATH = PROJECT_ROOT / "posts/video-posts/20260331-002427-一人食晚餐食谱/How To Cook If You're Single • Tasty_subtitled.mp4"
INDEXTTS2_DIR = PROJECT_ROOT / "submodules" / "IndexTTS-2"
NUM_SEGMENTS = 20


def parse_srt_segments(srt_path: Path, limit: int) -> list[str]:
    text = srt_path.read_text(encoding="utf-8")
    blocks = text.strip().split("\n\n")
    segments = []
    for block in blocks[:limit]:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        content = " ".join(lines[2:])
        content_clean = re.sub(r"\[.*?\]\s*", "", content).strip()
        if content_clean:
            segments.append(content_clean)
    return segments


def extract_reference_audio(video_path: Path, output_path: Path, duration: float = 10.0) -> Path:
    if output_path.exists():
        return output_path
    subprocess.run([
        "ffmpeg", "-i", str(video_path),
        "-t", str(duration), "-vn", "-ar", "22050", "-ac", "1",
        "-y", str(output_path),
    ], check=True, capture_output=True)
    return output_path


def concat_wavs(wav_paths: list[Path], output_path: Path) -> None:
    list_file = output_path.parent / f"{output_path.stem}_list.txt"
    list_file.write_text(
        "\n".join(f"file '{p}'" for p in wav_paths),
        encoding="utf-8",
    )
    subprocess.run([
        "ffmpeg", "-f", "concat", "-safe", "0",
        "-i", str(list_file), "-c", "copy", "-y", str(output_path),
    ], check=True, capture_output=True)
    list_file.unlink(missing_ok=True)


async def run_s2cpp_segments(segments: list[str], out_dir: Path, ref_audio: Path) -> float:
    import httpx
    from src.agents.video_post.utils.tts.providers.s2cpp import _ensure_s2cpp_server

    base_url = os.getenv("S2CPP_TTS_BASE_URL", "http://127.0.0.1:3030").strip().rstrip("/")
    await _ensure_s2cpp_server(base_url)

    params = {
        "max_new_tokens": 200,
        "temperature": 0.72,
        "top_p": 0.82,
        "top_k": 30,
        "n_threads": 4,
    }
    ref_text = " ".join(segments[:3])[:200]

    total_time = 0.0
    wav_paths = []
    async with httpx.AsyncClient() as client:
        for i, text in enumerate(segments):
            seg_path = out_dir / f"s2cpp_seg_{i:02d}.wav"
            start = time.perf_counter()
            with ref_audio.open("rb") as f:
                response = await client.post(
                    f"{base_url}/generate",
                    data={
                        "text": text,
                        "reference_text": ref_text,
                        "params": json.dumps(params),
                    },
                    files={"reference": ("ref.wav", f, "audio/wav")},
                    timeout=120.0,
                )
            elapsed = time.perf_counter() - start
            total_time += elapsed
            if response.status_code != 200:
                print(f"  seg {i} FAILED: HTTP {response.status_code}", flush=True)
                continue
            seg_path.write_bytes(response.content)
            wav_paths.append(seg_path)
            print(f"  seg {i}: {text[:20]}... {elapsed:.1f}s", flush=True)

    if wav_paths:
        concat_wavs(wav_paths, out_dir / "s2cpp_combined.wav")
    return total_time


def run_indextts2_segments(segments: list[str], out_dir: Path, ref_audio: Path) -> float:
    """Run IndexTTS-2 in its own venv, one segment at a time, model loaded once."""
    segments_json = json.dumps(segments, ensure_ascii=False)
    script = f'''
import sys, os, time, json, functools
os.environ["HF_HUB_CACHE"] = r"{INDEXTTS2_DIR / 'checkpoints' / 'hf_cache'}"
sys.path.insert(0, r"{INDEXTTS2_DIR}")

import torch
_orig_load = torch.load
@functools.wraps(_orig_load)
def _patched_load(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_load(*args, **kwargs)
torch.load = _patched_load
from indextts.infer_v2 import IndexTTS2

segments = json.loads(r"""{segments_json}""")

start = time.perf_counter()
tts = IndexTTS2(
    cfg_path=r"{INDEXTTS2_DIR / 'checkpoints' / 'config.yaml'}",
    model_dir=r"{INDEXTTS2_DIR / 'checkpoints'}",
    use_fp16=True,
    use_cuda_kernel=False,
    use_deepspeed=False,
)
print(f"  Model loaded in {{time.perf_counter() - start:.1f}}s", flush=True)

total_gen = 0.0
for i, text in enumerate(segments):
    out_path = r"{out_dir}" + f"\\\\indextts2_seg_{{i:02d}}.wav"
    seg_start = time.perf_counter()
    tts.infer(
        spk_audio_prompt=r"{ref_audio}",
        text=text,
        output_path=out_path,
        verbose=False,
        max_text_tokens_per_segment=120,
        use_emo_text=True,
        emo_alpha=0.6,
    )
    seg_time = time.perf_counter() - seg_start
    total_gen += seg_time
    print(f"  seg {{i}}: {{text[:20]}}... {{seg_time:.1f}}s", flush=True)

print(f"  Total generation: {{total_gen:.1f}}s", flush=True)
'''
    indextts_python = INDEXTTS2_DIR / ".venv" / "Scripts" / "python.exe"
    if not indextts_python.exists():
        raise FileNotFoundError(f"IndexTTS-2 venv not found: {indextts_python}")

    start = time.perf_counter()
    result = subprocess.run(
        [str(indextts_python), "-c", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600, cwd=str(INDEXTTS2_DIR),
    )
    elapsed = time.perf_counter() - start
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.returncode != 0:
        raise RuntimeError(f"exit {result.returncode}:\n{result.stderr[-1000:]}")

    # Concatenate
    wav_paths = sorted(out_dir.glob("indextts2_seg_*.wav"))
    if wav_paths:
        concat_wavs(wav_paths, out_dir / "indextts2_combined.wav")
    return elapsed


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    segments = parse_srt_segments(SRT_PATH, NUM_SEGMENTS)
    print(f"{len(segments)} segments to compare", flush=True)
    for i, seg in enumerate(segments):
        print(f"  {i}: {seg}", flush=True)
    print(flush=True)

    ref_audio = OUTPUT_DIR / "reference.wav"
    extract_reference_audio(VIDEO_PATH, ref_audio)
    print(f"Reference audio: {ref_audio}", flush=True)
    print(flush=True)

    # --- s2cpp ---
    s2cpp_dir = OUTPUT_DIR / "s2cpp"
    s2cpp_dir.mkdir(exist_ok=True)
    print("=== s2cpp (per-segment) ===", flush=True)
    try:
        elapsed = await run_s2cpp_segments(segments, s2cpp_dir, ref_audio)
        combined = s2cpp_dir / "s2cpp_combined.wav"
        if combined.exists():
            size = combined.stat().st_size / 1024
            print(f"  Combined: {size:.0f} KB, Total time: {elapsed:.1f}s", flush=True)
    except Exception as e:
        import traceback
        print(f"  FAILED: {e}", flush=True)
        traceback.print_exc()
    print(flush=True)

    # --- IndexTTS-2 ---
    indextts_dir = OUTPUT_DIR / "indextts2"
    indextts_dir.mkdir(exist_ok=True)
    print("=== IndexTTS-2 (per-segment, use_emo_text=True) ===", flush=True)
    try:
        elapsed = run_indextts2_segments(segments, indextts_dir, ref_audio)
        combined = indextts_dir / "indextts2_combined.wav"
        if combined.exists():
            size = combined.stat().st_size / 1024
            print(f"  Combined: {size:.0f} KB, Total time: {elapsed:.1f}s", flush=True)
    except Exception as e:
        print(f"  FAILED: {e}", flush=True)

    print(flush=True)
    print(f"Results in: {OUTPUT_DIR}", flush=True)
    print(f"  s2cpp:     {OUTPUT_DIR / 's2cpp' / 's2cpp_combined.wav'}", flush=True)
    print(f"  IndexTTS2: {OUTPUT_DIR / 'indextts2' / 'indextts2_combined.wav'}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
