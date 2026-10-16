#!/usr/bin/env python3
"""
mov2mp4 - Converter .mov -> .mp4 (file satuan atau batch folder), pakai ffmpeg.

Contoh:
  python mov2mp4.py video.mov                    # kualitas maksimal (default)
  python mov2mp4.py video.mov -q medium          # kualitas sedang, lebih kecil
  python mov2mp4.py video.mov -s 1080p           # turunkan ke 1920x1080 (sisi pendek 1080)
  python mov2mp4.py video.mov -s 720p -q medium  # 1280x720, kualitas sedang
  python mov2mp4.py video.mov -e                 # cuma estimasi ukuran, tanpa convert
  python mov2mp4.py video.mov -e --accurate      # estimasi lebih akurat (encode sampel pendek)
  python mov2mp4.py D:\\Videos -r -o D:\\Hasil    # batch satu folder + subfolder
  python mov2mp4.py D:\\Videos -r -g auto -j 2   # pakai GPU + 2 file paralel (lebih cepat)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Biar console Windows nggak error kalau ada karakter aneh di nama file
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

# Track audio yang tidak bisa di-decode ffmpeg / tidak cocok untuk mp4 (mis. spatial
# audio iPhone "apple_apac"). Track ini dibuang, track audio biasa (AAC) tetap dipakai.
UNSUPPORTED_AUDIO = {"apple_apac", "none", "unknown"}

# crf: makin kecil makin bagus (dan makin besar). bpp = perkiraan bits per pixel
# per frame, dipakai buat estimasi ukuran file hasil re-encode.
PROFILES = {
    "max": {"label": "Maksimal", "crf": 17, "preset": "slow", "abr": 256, "bpp": 0.14,
            "nvenc_cq": 19, "nvenc_preset": "p7",
            "qsv_q": 20, "qsv_preset": "veryslow",
            "amf_qp": 19, "amf_quality": "quality"},
    "medium": {"label": "Sedang", "crf": 23, "preset": "medium", "abr": 160, "bpp": 0.07,
               "nvenc_cq": 24, "nvenc_preset": "p4",
               "qsv_q": 25, "qsv_preset": "medium",
               "amf_qp": 24, "amf_quality": "balanced"},
}

# Encoder GPU yang didukung. "none" = CPU (libx264, paling lambat tapi paling kompatibel).
GPU_ENCODERS = {
    "nvenc": "h264_nvenc",   # NVIDIA
    "qsv": "h264_qsv",       # Intel Quick Sync
    "amf": "h264_amf",       # AMD
}

_print_lock = threading.Lock()
_encoders_cache = None


def available_encoders():
    """Daftar encoder yang didukung binary ffmpeg yang ada (hasil di-cache)."""
    global _encoders_cache
    if _encoders_cache is None:
        r = subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                           capture_output=True, text=True, errors="replace")
        _encoders_cache = r.stdout
    return _encoders_cache


def resolve_gpu(choice):
    """'auto' -> cari GPU encoder pertama yg didukung ffmpeg, fallback ke 'none' (CPU)."""
    enc_list = available_encoders()
    if choice == "auto":
        for key, name in GPU_ENCODERS.items():
            if name in enc_list:
                return key
        return "none"
    if choice != "none" and GPU_ENCODERS[choice] not in enc_list:
        print(f"Peringatan: ffmpeg di sistem ini tidak punya encoder {GPU_ENCODERS[choice]} "
              f"(biasanya butuh GPU + driver yang cocok). Pakai CPU (libx264) saja.")
        return "none"
    return choice

# Pilihan resolusi = batas sisi PENDEK video (jadi video portrait iPhone juga benar:
# 1080p -> 1920x1080 untuk landscape, 1080x1920 untuk portrait). Tidak pernah di-upscale.
SCALES = {"original": None, "1080p": 1080, "720p": 720, "480p": 480}

INSTALL_HELP = """\
ffmpeg / ffprobe tidak ketemu di PATH.

Cara install di Windows (pilih salah satu):
  winget install Gyan.FFmpeg
  choco install ffmpeg
  scoop install ffmpeg

Setelah install, TUTUP lalu buka lagi terminalnya, cek dengan: ffmpeg -version
"""


# ----------------------------------------------------------------- helpers
def fmt_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def fmt_dur(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


class Info:
    pass


def probe(path):
    cmd = [FFPROBE, "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "ffprobe gagal membaca file")
    data = json.loads(r.stdout)
    streams = data.get("streams", [])

    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise RuntimeError("tidak ada stream video di file ini")
    all_audio = [s for s in streams if s.get("codec_type") == "audio"]
    audios = [a for a in all_audio
              if a.get("codec_name", "unknown") not in UNSUPPORTED_AUDIO]

    i = Info()
    i.audio_idx = [a["index"] for a in audios]
    i.skipped_audio = [a.get("codec_name", "?") for a in all_audio
                       if a.get("codec_name", "unknown") in UNSUPPORTED_AUDIO]
    i.path = Path(path)
    i.size = int(data["format"].get("size") or Path(path).stat().st_size)
    i.duration = float(data["format"].get("duration") or video.get("duration") or 0)
    i.vcodec = video.get("codec_name", "?")
    i.pix_fmt = video.get("pix_fmt", "")
    i.width = int(video.get("width") or 0)
    i.height = int(video.get("height") or 0)
    # Video iPhone portrait biasanya disimpan landscape + flag rotasi; ffmpeg otomatis
    # memutarnya saat encode, jadi ukuran "tampil" = ukuran setelah rotasi.
    rot = 0
    for sd in video.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(round(float(sd["rotation"])))
            except (ValueError, TypeError):
                pass
    if not rot:
        try:
            rot = int((video.get("tags") or {}).get("rotate", 0))
        except (ValueError, TypeError):
            rot = 0
    swap = abs(rot) % 180 == 90
    i.dw, i.dh = (i.height, i.width) if swap else (i.width, i.height)
    num, _, den = (video.get("avg_frame_rate") or "0/1").partition("/")
    try:
        i.fps = float(num) / float(den or 1) or 30.0
    except (ValueError, ZeroDivisionError):
        i.fps = 30.0
    i.acodecs = [a.get("codec_name", "?") for a in audios]
    abr_src = 0
    for a in audios:
        try:
            abr_src += int(a.get("bit_rate") or 0)
        except ValueError:
            pass
    i.abr_src = abr_src or len(audios) * 128_000
    return i


def target_size(info, scale_key):
    """Return (lebar, tinggi, apakah_diperkecil) setelah pilihan resolusi diterapkan."""
    limit = SCALES.get(scale_key)
    short = min(info.dw, info.dh)
    if not limit or short <= limit:
        return info.dw, info.dh, False
    f = limit / short
    return round(info.dw * f / 2) * 2, round(info.dh * f / 2) * 2, True


def scale_filter(scale_key):
    """Filter ffmpeg: sisi pendek jadi <= limit, rasio asli terjaga, lebar/tinggi genap."""
    t = SCALES[scale_key]
    return (f"scale=w='if(gt(iw,ih),-2,min(iw,{t}))':"
            f"h='if(gt(iw,ih),min(ih,{t}),-2)':flags=lanczos")


def make_plan(info, mode, scaled=False):
    """Tentukan: video di-copy atau di-encode ulang, audio di-copy atau di-AAC-kan."""
    video_ok = info.vcodec == "h264" and info.pix_fmt in ("yuv420p", "yuvj420p")
    warn = None
    if mode == "reencode":
        vcopy = False
    elif mode == "copy":
        vcopy = video_ok
        if not video_ok:
            warn = (f"video {info.vcodec}/{info.pix_fmt} tidak bisa di-copy aman ke mp4, "
                    "pakai re-encode")
    else:
        vcopy = video_ok
    if scaled:  # ganti resolusi mustahil tanpa re-encode
        if vcopy and mode == "copy":
            warn = "ganti resolusi butuh re-encode, mode copy diabaikan"
        vcopy = False
    acopy = all(c == "aac" for c in info.acodecs)  # True juga kalau tanpa audio
    return vcopy, acopy, warn


def video_args(prof, scale_key="original", gpu="none"):
    args = []
    if SCALES.get(scale_key):
        args += ["-vf", scale_filter(scale_key)]
    if gpu == "nvenc":
        return args + ["-c:v", "h264_nvenc", "-preset", prof["nvenc_preset"],
                       "-rc", "vbr", "-cq", str(prof["nvenc_cq"]), "-b:v", "0",
                       "-profile:v", "high", "-pix_fmt", "yuv420p"]
    if gpu == "qsv":
        return args + ["-c:v", "h264_qsv", "-preset", prof["qsv_preset"],
                       "-global_quality", str(prof["qsv_q"]),
                       "-profile:v", "high", "-pix_fmt", "nv12"]
    if gpu == "amf":
        return args + ["-c:v", "h264_amf", "-quality", prof["amf_quality"], "-rc", "cqp",
                       "-qp_i", str(prof["amf_qp"]), "-qp_p", str(prof["amf_qp"]),
                       "-profile:v", "high", "-pix_fmt", "yuv420p"]
    return args + ["-c:v", "libx264", "-preset", prof["preset"], "-crf", str(prof["crf"]),
                   "-profile:v", "high", "-pix_fmt", "yuv420p"]


def estimate(info, prof, vcopy, acopy, out_w=None, out_h=None):
    """Return (low, mid, high) dalam bytes. Untuk copy ukurannya pasti ~sama."""
    dur = info.duration
    n_audio = len(info.acodecs)
    audio_bytes = (info.abr_src if acopy else n_audio * prof["abr"] * 1000) * dur / 8
    if vcopy:
        video_bytes = max(0, info.size - info.abr_src * dur / 8)
        total = video_bytes + audio_bytes
        return total * 0.99, total, total * 1.01
    px = (out_w or info.dw) * (out_h or info.dh)
    mid_bps = prof["bpp"] * px * info.fps
    mid = mid_bps * dur / 8 + audio_bytes
    low = mid_bps * 0.5 * dur / 8 + audio_bytes
    high = mid_bps * 1.6 * dur / 8 + audio_bytes
    return low, mid, high


def sample_estimate(info, prof, acopy, scale_key="original", gpu="none"):
    """Estimasi lebih akurat: encode 3 klip pendek (6 detik) lalu ekstrapolasi."""
    n, clip = 3, 6
    if info.duration < n * clip * 2:
        return None
    total = 0
    with tempfile.TemporaryDirectory() as d:
        for k in range(n):
            t = min(info.duration * (0.15 + 0.35 * k), info.duration - clip - 1)
            out = Path(d) / f"s{k}.mp4"
            cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                   "-ss", f"{t:.2f}", "-i", str(info.path), "-t", str(clip),
                   "-map", "0:v:0", "-an", *video_args(prof, scale_key, gpu), str(out)]
            if subprocess.run(cmd, capture_output=True).returncode != 0:
                return None
            total += out.stat().st_size
    video_bytes = total / (n * clip) * info.duration
    audio_bytes = (info.abr_src if acopy else len(info.acodecs) * prof["abr"] * 1000) * info.duration / 8
    return video_bytes + audio_bytes


def print_estimate(info, prof, vcopy, acopy, accurate, scale_key="original", gpu="none", quiet=False):
    out_w, out_h, _ = target_size(info, scale_key)
    low, mid, high = estimate(info, prof, vcopy, acopy, out_w, out_h)
    if vcopy:
        print(f"  Estimasi ukuran: ~{fmt_size(mid)} (video tidak di-encode ulang)")
        return
    print(f"  Estimasi ukuran: {fmt_size(low)} - {fmt_size(high)} (tengah ~{fmt_size(mid)}, "
          f"asli {fmt_size(info.size)})")
    if accurate:
        if not quiet:
            print("  Menghitung estimasi akurat (encode 3 sampel pendek)...", end="", flush=True)
        s = sample_estimate(info, prof, acopy, scale_key, gpu)
        if not quiet:
            print("\r" + " " * 70 + "\r", end="")
        if s:
            print(f"  Estimasi akurat: ~{fmt_size(s)} (+/- 15%)")
        else:
            print("  Estimasi akurat: video terlalu pendek / gagal sampling, pakai rentang di atas")


# -------------------------------------------------------------- konversi
def run_ffmpeg(cmd, duration, quiet=False, tag=""):
    proc = subprocess.Popen(cmd + ["-progress", "pipe:1", "-nostats"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    errors = []
    start = time.time()
    try:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us="):
                if quiet:  # paralel: jangan print progress per-frame, biar nggak tabrakan
                    continue
                try:
                    done = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                if duration > 0:
                    pct = min(100.0, done / duration * 100)
                    elapsed = time.time() - start
                    eta = (elapsed / pct * (100 - pct)) if pct > 1 else 0
                    print(f"\r  {tag}Progress: {pct:5.1f}%  sisa ~{fmt_dur(eta)}   ", end="", flush=True)
            elif "=" not in line and line:
                errors.append(line)
        proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        raise
    if not quiet:
        print("\r" + " " * 60 + "\r", end="")
    return proc.returncode, errors[-10:]


def convert_one(src, dst, prof, mode, scale_key, force, estimate_only, accurate,
                gpu="none", quiet=False, tag=""):
    buf = []
    p = (lambda s: buf.append(s)) if quiet else print

    info = probe(src)
    out_w, out_h, scaled = target_size(info, scale_key)
    vcopy, acopy, warn = make_plan(info, mode, scaled)

    enc_label = {"nvenc": "NVIDIA NVENC", "qsv": "Intel QSV", "amf": "AMD AMF"}.get(gpu)
    how = ("remux (tanpa re-encode)" if vcopy and acopy else
           "video di-copy, audio -> AAC" if vcopy else
           f"re-encode H.264 via {enc_label}" if enc_label else
           f"re-encode H.264 CRF {prof['crf']} / preset {prof['preset']} (CPU)")
    p(f"  {info.width}x{info.height} @ {info.fps:.2f}fps, {fmt_dur(info.duration)}, "
      f"{info.vcodec}, audio: {','.join(info.acodecs) or 'tidak ada'}")
    p(f"  Metode: {how}")
    if scaled:
        p(f"  Resolusi: {info.dw}x{info.dh} -> {out_w}x{out_h} ({scale_key})")
    elif SCALES.get(scale_key):
        p(f"  Resolusi: {info.dw}x{info.dh} sudah <= {scale_key}, tidak diubah")
    if warn:
        p(f"  Catatan: {warn}")
    if info.skipped_audio:
        p(f"  Catatan: track audio {','.join(info.skipped_audio)} dilewati "
          "(tidak didukung), pakai track audio lainnya")
    if not quiet:
        print_estimate(info, prof, vcopy, acopy, accurate, scale_key, gpu, quiet)

    if estimate_only:
        if quiet:
            with _print_lock:
                print(f"[{tag}] {src}"); [print(line) for line in buf]; print()
        return "estimated", info.size, 0

    if dst.exists() and not force:
        p(f"  SKIP: {dst.name} sudah ada (pakai --force untuk timpa)")
        if quiet:
            with _print_lock:
                print(f"[{tag}] {src}"); [print(line) for line in buf]; print()
        return "skipped", info.size, 0

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + f".part{threading.get_ident()}.mp4")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
           "-map", "0:v:0"]
    for idx in info.audio_idx:
        cmd += ["-map", f"0:{idx}"]
    cmd += ["-sn", "-dn", "-map_metadata", "0"]
    cmd += ["-c:v", "copy"] if vcopy else video_args(prof, scale_key, gpu)
    cmd += ["-c:a", "copy"] if acopy else ["-c:a", "aac", "-b:a", f"{prof['abr']}k"]
    cmd += ["-movflags", "+faststart", str(tmp)]

    if quiet:
        with _print_lock:
            print(f"[{tag}] mulai: {src}")

    try:
        code, errs = run_ffmpeg(cmd, info.duration, quiet, tag=f"{tag} " if tag else "")
    except KeyboardInterrupt:
        tmp.unlink(missing_ok=True)
        raise
    if code != 0:
        tmp.unlink(missing_ok=True)
        if quiet:
            with _print_lock:
                print(f"[{tag}] {src}"); [print(line) for line in buf]
        raise RuntimeError("ffmpeg gagal:\n    " + "\n    ".join(errs))

    os.replace(tmp, dst)
    out_size = dst.stat().st_size
    ratio = out_size / info.size * 100 if info.size else 0
    p(f"  Selesai: {dst}  ({fmt_size(out_size)}, {ratio:.0f}% dari ukuran asli)")
    if quiet:
        with _print_lock:
            print(f"[{tag}] {src}"); [print(line) for line in buf]; print()
    return "done", info.size, out_size


# ------------------------------------------------------------------ main
def collect(src, recursive):
    if src.is_file():
        return [src]
    it = src.rglob("*") if recursive else src.glob("*")
    return sorted(p for p in it if p.is_file() and p.suffix.lower() == ".mov")


def main():
    ap = argparse.ArgumentParser(description="Konversi .mov ke .mp4 pakai ffmpeg.")
    ap.add_argument("input", help="file .mov atau folder berisi .mov")
    ap.add_argument("-o", "--output", help="file .mp4 tujuan (untuk 1 file) atau folder tujuan")
    ap.add_argument("-q", "--quality", choices=PROFILES, default="max",
                    help="max = CRF 17 (hampir tanpa loss), medium = CRF 23 (lebih kecil). Default: max")
    ap.add_argument("-m", "--mode", choices=["auto", "copy", "reencode"], default="auto",
                    help="auto: remux kalau video sudah H.264, selain itu re-encode. "
                         "reencode: paksa encode ulang (mis. biar medium benar-benar mengecilkan file)")
    ap.add_argument("-s", "--scale", choices=list(SCALES), default="original",
                    help="turunkan resolusi: 1080p (1920x1080), 720p (1280x720), 480p. "
                         "Video yang sudah lebih kecil tidak diubah. Default: original")
    ap.add_argument("-r", "--recursive", action="store_true", help="masuk ke subfolder (mode folder)")
    ap.add_argument("-f", "--force", action="store_true", help="timpa file .mp4 yang sudah ada")
    ap.add_argument("-e", "--estimate", action="store_true", help="hanya tampilkan estimasi ukuran")
    ap.add_argument("--accurate", action="store_true",
                    help="estimasi lebih akurat dengan encode 3 sampel pendek (lebih lama)")
    ap.add_argument("-g", "--gpu", choices=["auto", "none", "nvenc", "qsv", "amf"], default="none",
                    help="encode pakai GPU (jauh lebih cepat dari CPU). auto: pakai GPU pertama yang "
                         "kedetek (NVIDIA/Intel/AMD). none = CPU/libx264 (default, paling kompatibel)")
    ap.add_argument("-j", "--jobs", type=int, default=1,
                    help="jumlah file yang dikonversi bersamaan saat batch folder (default: 1). "
                         "Naikkan kalau pakai GPU atau CPU banyak core; terlalu tinggi bisa malah "
                         "lebih lambat kalau encode-nya CPU-bound")
    args = ap.parse_args()

    if not FFMPEG or not FFPROBE:
        print(INSTALL_HELP)
        return 2

    gpu = resolve_gpu(args.gpu)

    src = Path(args.input).expanduser()
    if not src.exists():
        print(f"Tidak ditemukan: {src}")
        return 2

    files = collect(src, args.recursive)
    if not files:
        print("Tidak ada file .mov ditemukan" + ("" if args.recursive or src.is_file()
                                                  else " (coba tambah -r untuk subfolder)"))
        return 1

    out_arg = Path(args.output).expanduser() if args.output else None
    if out_arg and src.is_dir() and out_arg.suffix.lower() == ".mp4":
        print("Untuk mode folder, -o harus berupa folder, bukan file .mp4")
        return 2

    prof = PROFILES[args.quality]
    gpu_note = f" | GPU: {gpu}" if gpu != "none" else " | GPU: tidak dipakai (CPU)"
    jobs_note = f" | Paralel: {args.jobs}x" if args.jobs > 1 else ""
    print(f"Profil: {prof['label']} | Mode: {args.mode} | Resolusi: {args.scale}{gpu_note}"
          f"{jobs_note} | {len(files)} file\n")

    def dst_for(f):
        if src.is_file():
            if out_arg and out_arg.suffix.lower() == ".mp4":
                return out_arg
            if out_arg:
                return out_arg / (f.stem + ".mp4")
            return f.with_suffix(".mp4")
        rel = f.relative_to(src).with_suffix(".mp4")
        return (out_arg or src) / rel

    stats = {"done": 0, "skipped": 0, "estimated": 0, "failed": 0}
    total_in = total_out = 0
    parallel = args.jobs > 1 and len(files) > 1

    try:
        if not parallel:
            for n, f in enumerate(files, 1):
                dst = dst_for(f)
                print(f"[{n}/{len(files)}] {f}")
                try:
                    status, s_in, s_out = convert_one(f, dst, prof, args.mode, args.scale,
                                                      args.force, args.estimate, args.accurate, gpu)
                    stats[status] += 1
                    if status == "done":
                        total_in += s_in
                        total_out += s_out
                except Exception as e:  # satu file gagal, lanjut ke berikutnya
                    stats["failed"] += 1
                    print(f"  GAGAL: {e}")
                print()
        else:
            with ThreadPoolExecutor(max_workers=args.jobs) as ex:
                futs = {}
                for n, f in enumerate(files, 1):
                    dst = dst_for(f)
                    tag = f"{n}/{len(files)}"
                    fut = ex.submit(convert_one, f, dst, prof, args.mode, args.scale,
                                    args.force, args.estimate, args.accurate, gpu, True, tag)
                    futs[fut] = f
                for fut in as_completed(futs):
                    try:
                        status, s_in, s_out = fut.result()
                        stats[status] += 1
                        if status == "done":
                            total_in += s_in
                            total_out += s_out
                    except Exception as e:
                        stats["failed"] += 1
                        with _print_lock:
                            print(f"  GAGAL ({futs[fut]}): {e}\n")
    except KeyboardInterrupt:
        print("\nDibatalkan (Ctrl+C). File sementara sudah dibersihkan.")
        return 130

    print("=== Ringkasan ===")
    print(f"Selesai: {stats['done']} | Skip: {stats['skipped']} | Gagal: {stats['failed']}"
          + (f" | Hanya estimasi: {stats['estimated']}" if stats["estimated"] else ""))
    if stats["done"]:
        print(f"Total: {fmt_size(total_in)} -> {fmt_size(total_out)}")
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
