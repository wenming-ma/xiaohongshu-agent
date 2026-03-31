import time
import sys

print("Step 1: importing...", flush=True)
from indextts.infer_v2 import IndexTTS2

print("Step 2: creating model (no emo_text)...", flush=True)
start = time.perf_counter()
try:
    tts = IndexTTS2(
        cfg_path="checkpoints/config.yaml",
        model_dir="checkpoints",
        use_fp16=True,
        use_cuda_kernel=False,
        use_deepspeed=False,
    )
    print(f"Step 3: model loaded in {time.perf_counter()-start:.1f}s", flush=True)
except Exception as e:
    print(f"FAILED at model load: {e}", flush=True)
    sys.exit(1)

print("Step 4: running inference (no emo_text)...", flush=True)
start = time.perf_counter()
try:
    tts.infer(
        spk_audio_prompt=r"C:\Users\wenming\source\repos\xiaohongshu-agent\posts\video-posts\20260331-002427-一人食晚餐食谱\tts_compare\reference.wav",
        text="为什么我单身",
        output_path=r"C:\Users\wenming\source\repos\xiaohongshu-agent\posts\video-posts\20260331-002427-一人食晚餐食谱\tts_compare\indextts2\test_single.wav",
    )
    print(f"Step 5: inference done in {time.perf_counter()-start:.1f}s", flush=True)
except Exception as e:
    print(f"FAILED at inference: {e}", flush=True)
    sys.exit(1)

print("ALL DONE", flush=True)
