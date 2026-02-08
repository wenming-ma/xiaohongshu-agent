"""
下载并验证 Faster-Whisper 模型

运行方式:
    uv run python scripts/download_whisper_model.py
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

from faster_whisper import WhisperModel

def main():
    print("=" * 60)
    print("Faster-Whisper large-v3 Model Download")
    print("=" * 60)
    print()

    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
    print(f"Cache directory: {cache_dir}")
    print("Model size: ~3GB")
    print()

    try:
        print("Loading model from cache...")
        print()

        model = WhisperModel(
            "large-v3",
            device="cuda",
            compute_type="float16",
            download_root=str(cache_dir),
        )
        print()
        print("Model loaded successfully!")
        print()

        print("Model info:")
        print(f"  - Model: large-v3")
        print(f"  - Device: CUDA (GPU)")
        print(f"  - Compute type: float16")
        print()

        print("Verification complete! Ready to use.")

    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Solutions:")
        print("  1. Check network connection")
        print("  2. For China users, set proxy:")
        print("     set HF_ENDPOINT=https://hf-mirror.com")
        print("  3. Or use smaller model in settings.py:")
        print("     WHISPER_MODEL='base'")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
