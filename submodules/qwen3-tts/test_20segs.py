"""Generate first 20 subtitle segments with Qwen3-TTS CustomVoice."""

import gc
import os
import re
import time
from pathlib import Path

# Disable safetensors mmap to avoid paging file issues on low-RAM Windows
os.environ["SAFETENSORS_FAST_GPU"] = "1"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRT_PATH = PROJECT_ROOT / "posts/video-posts/20260331-002427-一人食晚餐食谱/How To Cook If You're Single • Tasty_subtitled_tts.srt"
OUTPUT_DIR = PROJECT_ROOT / "posts/video-posts/20260331-002427-一人食晚餐食谱/tts_compare/qwen3tts"
REF_AUDIO = PROJECT_ROOT / "posts/video-posts/20260331-002427-一人食晚餐食谱/tts_compare/reference.wav"
NUM_SEGMENTS = 20

TAG_TO_INSTRUCT = {
    "questioning": "用疑惑好奇的语气说",
    "playful": "用俏皮活泼的语气说",
    "friendly": "用亲切友好的语气说",
    "matter of fact": "用平淡陈述的语气说",
    "casual": "用轻松随意的语气说",
    "confident": "用自信的语气说",
    "excited": "用兴奋激动的语气说",
    "neutral": "",
}


def parse_srt_segments(srt_path: Path, limit: int) -> list[dict]:
    text = srt_path.read_text(encoding="utf-8")
    blocks = text.strip().split("\n\n")
    segments = []
    for block in blocks[:limit]:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        content = " ".join(lines[2:])
        tag_match = re.match(r"\[([^\]]+)\]\s*", content)
        tag = tag_match.group(1) if tag_match else "neutral"
        text_clean = re.sub(r"\[.*?\]\s*", "", content).strip()
        if text_clean:
            segments.append({"text": text_clean, "tag": tag})
    return segments


def _patch_safe_open():
    """Monkey-patch safetensors.safe_open to avoid mmap on Windows with low RAM."""
    import safetensors
    from safetensors.torch import load_file
    _original_safe_open = safetensors.safe_open

    class _DirectLoadSafeOpen:
        def __init__(self, filename, framework="pt", device="cpu"):
            self._data = load_file(filename, device=device)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def keys(self):
            return self._data.keys()

        def get_tensor(self, name):
            return self._data[name]

        def metadata(self):
            return {}

    safetensors.safe_open = _DirectLoadSafeOpen
    # Also patch the reference in transformers
    import transformers.modeling_utils as tmu
    if hasattr(tmu, 'safe_open'):
        tmu.safe_open = _DirectLoadSafeOpen


def main():
    import torch
    import soundfile as sf

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    segments = parse_srt_segments(SRT_PATH, NUM_SEGMENTS)
    print(f"{len(segments)} segments to generate", flush=True)

    gc.collect()
    torch.cuda.empty_cache()

    # Patch safetensors to avoid mmap
    _patch_safe_open()

    from qwen_tts import Qwen3TTSModel

    print("Loading Qwen3-TTS model...", flush=True)
    load_start = time.perf_counter()
    model = Qwen3TTSModel.from_pretrained(
        "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        device_map="cuda:0",
        dtype=torch.float16,
    )
    print(f"Model loaded in {time.perf_counter() - load_start:.1f}s", flush=True)

    # Create voice clone prompt from reference audio
    print("Creating voice clone prompt...", flush=True)
    voice_clone_prompt = model.create_voice_clone_prompt(str(REF_AUDIO))
    print("Voice clone prompt ready", flush=True)

    # Generate each segment
    total_gen = 0.0
    wav_paths = []
    for i, seg in enumerate(segments):
        instruct = TAG_TO_INSTRUCT.get(seg["tag"], "")
        print(f"  seg {i}: [{seg['tag']}] {seg['text'][:30]}... instruct='{instruct}'", flush=True)

        gen_start = time.perf_counter()
        wavs, sr = model.generate_voice_clone(
            text=seg["text"],
            voice_clone_prompt=voice_clone_prompt,
            instruct=instruct,
        )
        gen_time = time.perf_counter() - gen_start
        total_gen += gen_time

        seg_path = OUTPUT_DIR / f"seg_{i:02d}.wav"
        sf.write(str(seg_path), wavs[0], sr)
        wav_paths.append(seg_path)
        print(f"    -> {gen_time:.1f}s, {len(wavs[0])/sr:.1f}s audio", flush=True)

    print(f"\nTotal generation time: {total_gen:.1f}s", flush=True)

    # Concatenate all segments
    import numpy as np
    all_wavs = []
    for p in wav_paths:
        data, _ = sf.read(str(p))
        all_wavs.append(data)
        all_wavs.append(np.zeros(int(sr * 0.2)))

    combined = np.concatenate(all_wavs)
    combined_path = OUTPUT_DIR / "qwen3tts_combined.wav"
    sf.write(str(combined_path), combined, sr)
    print(f"Combined: {combined_path} ({len(combined)/sr:.1f}s)", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
