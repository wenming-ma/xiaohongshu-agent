import argparse
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class Segment:
    start: float
    end: float
    text: str


def parse_timecode(tc: str) -> float:
    # 00:01:02,345
    hms, ms = tc.split(",")
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(srt_path: Path) -> list[Segment]:
    blocks = srt_path.read_text(encoding="utf-8", errors="ignore").strip().split("\n\n")
    out: list[Segment] = []
    for block in blocks:
        lines = [ln.strip("\ufeff").strip() for ln in block.splitlines()]
        if len(lines) < 3:
            continue
        if "-->" not in lines[1]:
            continue
        start_tc, end_tc = [x.strip() for x in lines[1].split("-->", 1)]
        text = " ".join(x for x in lines[2:] if x).strip()
        text = " ".join(text.split())
        if not text:
            continue
        start = parse_timecode(start_tc)
        end = parse_timecode(end_tc)
        if end <= start:
            continue
        out.append(Segment(start=start, end=end, text=text))
    return out


def merge_segments(
    segments: list[Segment],
    max_gap: float = 0.35,
    max_duration: float = 7.5,
    max_chars: int = 52,
) -> list[Segment]:
    if not segments:
        return []
    merged: list[Segment] = []
    cur = Segment(segments[0].start, segments[0].end, segments[0].text)
    for seg in segments[1:]:
        gap = seg.start - cur.end
        candidate_duration = seg.end - cur.start
        candidate_chars = len(cur.text) + 1 + len(seg.text)
        if gap <= max_gap and candidate_duration <= max_duration and candidate_chars <= max_chars:
            cur.end = seg.end
            cur.text = f"{cur.text} {seg.text}".strip()
        else:
            merged.append(cur)
            cur = Segment(seg.start, seg.end, seg.text)
    merged.append(cur)
    return merged


def run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def get_video_duration(video_path: Path) -> float:
    p = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(p.stdout.strip())


def wait_server(base_url: str, timeout_s: float = 120.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/", timeout=2.0)
            if r.status_code in (200, 404):
                return
        except Exception:
            pass
        time.sleep(1.0)
    raise RuntimeError(f"s2 server not ready: {base_url}")


def synthesize_segment(
    client: httpx.Client,
    base_url: str,
    reference_audio: Path,
    reference_text: str,
    text: str,
    max_new_tokens: int,
    output_wav: Path,
    retries: int = 3,
) -> None:
    last_err: Exception | None = None
    for _ in range(retries):
        try:
            with reference_audio.open("rb") as f:
                files = {"reference": ("reference.wav", f, "audio/wav")}
                params = {
                    "max_new_tokens": max_new_tokens,
                    "temperature": 0.72,
                    "top_p": 0.82,
                    "top_k": 30,
                    "min_tokens_before_end": 0,
                    "n_threads": 4,
                }
                data = {
                    "text": text,
                    "reference_text": reference_text,
                    "params": json.dumps(params, ensure_ascii=False),
                }
                r = client.post(f"{base_url}/generate", data=data, files=files, timeout=240.0)
                r.raise_for_status()
                output_wav.write_bytes(r.content)
                return
        except Exception as e:  # pragma: no cover - runtime guard
            last_err = e
            time.sleep(1.0)
    raise RuntimeError(f"s2 generate failed: {last_err!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Chinese dubbing with s2.cpp server + SRT")
    parser.add_argument("--video", required=True)
    parser.add_argument("--srt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--s2-root", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--reference-audio", required=True)
    parser.add_argument("--reference-text-file", required=True)
    parser.add_argument("--port", type=int, default=3030)
    parser.add_argument("--cuda-device", type=int, default=0)
    parser.add_argument("--bg-volume", type=float, default=0.35)
    parser.add_argument("--tokens-per-second", type=float, default=30.0)
    parser.add_argument("--merge-max-gap", type=float, default=0.35)
    parser.add_argument("--merge-max-duration", type=float, default=7.5)
    parser.add_argument("--merge-max-chars", type=int, default=52)
    args = parser.parse_args()

    video_path = Path(args.video).resolve()
    srt_path = Path(args.srt).resolve()
    output_path = Path(args.output).resolve()
    work_dir = Path(args.work_dir).resolve()
    s2_root = Path(args.s2_root).resolve()
    model_path = Path(args.model).resolve()
    tokenizer_path = Path(args.tokenizer).resolve()
    ref_audio = Path(args.reference_audio).resolve()
    ref_text_path = Path(args.reference_text_file).resolve()

    for p in [video_path, srt_path, model_path, tokenizer_path, ref_audio, ref_text_path]:
        if not p.exists():
            raise FileNotFoundError(str(p))

    work_dir.mkdir(parents=True, exist_ok=True)
    seg_dir = work_dir / "s2_segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    mix_dir = work_dir / "s2_mix"
    mix_dir.mkdir(parents=True, exist_ok=True)

    reference_text = ref_text_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not reference_text:
        raise RuntimeError("reference text is empty")

    segments = parse_srt(srt_path)
    merged = merge_segments(
        segments,
        max_gap=args.merge_max_gap,
        max_duration=args.merge_max_duration,
        max_chars=args.merge_max_chars,
    )
    print(f"segments parsed={len(segments)} merged={len(merged)}", flush=True)

    if not merged:
        raise RuntimeError("no subtitle segments")

    duration = get_video_duration(video_path)
    print(f"video duration={duration:.3f}s", flush=True)

    dll_dir = s2_root / "build-cuda" / "bin" / "Release"
    s2_exe = s2_root / "build-cuda" / "Release" / "s2.exe"
    if not s2_exe.exists():
        raise FileNotFoundError(str(s2_exe))

    # Keep inherited PATH and prepend ggml cuda/cpu dll path for s2.exe runtime.
    env = dict(os.environ)
    env["PATH"] = f"{dll_dir};{env.get('PATH', '')}"

    server_cmd = [
        str(s2_exe),
        "-m",
        str(model_path),
        "-t",
        str(tokenizer_path),
        "-c",
        str(args.cuda_device),
        "--server",
        "-H",
        "127.0.0.1",
        "-P",
        str(args.port),
    ]

    server_proc = subprocess.Popen(
        server_cmd,
        cwd=str(s2_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{args.port}"
    try:
        wait_server(base_url, timeout_s=180.0)
        with httpx.Client() as client:
            aligned_files: list[tuple[float, Path]] = []
            for i, seg in enumerate(merged, start=1):
                dur = max(0.2, seg.end - seg.start)
                max_tokens = int(max(80, min(260, round(dur * args.tokens_per_second))))
                raw_wav = seg_dir / f"seg_{i:04d}_raw.wav"
                ali_wav = seg_dir / f"seg_{i:04d}.wav"
                synthesize_segment(
                    client=client,
                    base_url=base_url,
                    reference_audio=ref_audio,
                    reference_text=reference_text,
                    text=seg.text,
                    max_new_tokens=max_tokens,
                    output_wav=raw_wav,
                )
                run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "error",
                        "-i",
                        str(raw_wav),
                        "-af",
                        f"atrim=0:{dur:.3f},apad=pad_dur={dur:.3f}",
                        "-t",
                        f"{dur:.3f}",
                        str(ali_wav),
                    ]
                )
                aligned_files.append((seg.start, ali_wav))
                if i % 10 == 0 or i == len(merged):
                    print(f"s2 progress {i}/{len(merged)}", flush=True)

        acc = mix_dir / "acc_0000.wav"
        run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-t",
                f"{duration:.3f}",
                "-i",
                "anullsrc=channel_layout=mono:sample_rate=44100",
                str(acc),
            ]
        )

        for i, (start_sec, seg_wav) in enumerate(aligned_files, start=1):
            nxt = mix_dir / f"acc_{i:04d}.wav"
            d_ms = int(round(start_sec * 1000.0))
            run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(acc),
                    "-i",
                    str(seg_wav),
                    "-filter_complex",
                    f"[1:a]adelay={d_ms}|{d_ms}[a1];[0:a][a1]amix=inputs=2:normalize=0[out]",
                    "-map",
                    "[out]",
                    str(nxt),
                ]
            )
            acc = nxt
            if i % 20 == 0 or i == len(aligned_files):
                print(f"mix progress {i}/{len(aligned_files)}", flush=True)

        dubbed_wav = work_dir / "dubbed_s2.wav"
        shutil.copy2(acc, dubbed_wav)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(video_path),
                "-i",
                str(dubbed_wav),
                "-filter_complex",
                f"[0:a]volume={args.bg_volume:.3f}[bg];[bg][1:a]amix=inputs=2:normalize=0[mix]",
                "-map",
                "0:v",
                "-map",
                "[mix]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                str(output_path),
            ]
        )

        sidecar_srt = output_path.with_suffix(".srt")
        shutil.copy2(srt_path, sidecar_srt)

        print(f"done: {output_path}", flush=True)
        print(f"sidecar srt: {sidecar_srt}", flush=True)
        return 0
    finally:
        if server_proc.poll() is None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
