#!/usr/bin/env python3
"""
mov2mp4_gui.py - Antarmuka Grafis (GUI Tkinter) untuk mov2mp4.
Memudahkan konversi video .mov ke .mp4 secara batch atau satuan.
"""

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

# Pastikan direktori script ada di sys.path agar impor mov2mp4 selalu berhasil
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from mov2mp4 import (
    FFMPEG,
    FFPROBE,
    GPU_ENCODERS,
    PROFILES,
    SCALES,
    collect,
    estimate,
    fmt_dur,
    fmt_size,
    make_plan,
    probe,
    resolve_gpu,
    sample_estimate,
    target_size,
    video_args,
)


class Mov2Mp4GUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("mov2mp4 - Video Converter")
        self.root.geometry("680x640")
        self.root.minsize(600, 520)

        # Threading & Komunikasi
        self.queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker_thread = None
        self.current_proc = None
        self.current_tmp = None
        self.is_running = False

        # Variabel Form
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.quality_var = tk.StringVar(value="max")
        self.scale_var = tk.StringVar(value="original")
        self.mode_var = tk.StringVar(value="auto")
        self.gpu_var = tk.StringVar(value="auto")
        self.recursive_var = tk.BooleanVar(value=False)
        self.force_var = tk.BooleanVar(value=False)
        self.accurate_var = tk.BooleanVar(value=False)

        # Variabel Status & Progress
        self.status_var = tk.StringVar(value="Siap")
        self.progress_info_var = tk.StringVar(value="0.0% | ETA: --:--")

        # Inisialisasi UI
        self._build_ui()

        # Handler saat window ditutup
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Mulai antrean pemrosesan event UI
        self.root.after(50, self._process_queue)

        # Cek ketersediaan ffmpeg saat startup
        self._check_dependencies()

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding="10 10 10 10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(5, weight=1)

        # ---------------- 1. Frame Input ----------------
        input_frame = ttk.LabelFrame(main_frame, text="Sumber Input (.mov atau Folder)", padding=8)
        input_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        input_frame.columnconfigure(1, weight=1)

        ttk.Label(input_frame, text="Input:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        self.entry_input = ttk.Entry(input_frame, textvariable=self.input_var)
        self.entry_input.grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=2)

        self.btn_browse_in_file = ttk.Button(input_frame, text="Pilih File...", command=self._browse_input_file)
        self.btn_browse_in_file.grid(row=0, column=2, padx=(0, 4), pady=2)

        self.btn_browse_in_dir = ttk.Button(input_frame, text="Pilih Folder...", command=self._browse_input_dir)
        self.btn_browse_in_dir.grid(row=0, column=3, pady=2)

        # ---------------- 2. Frame Output ----------------
        output_frame = ttk.LabelFrame(main_frame, text="Folder Output (Opsional)", padding=8)
        output_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        output_frame.columnconfigure(1, weight=1)

        ttk.Label(output_frame, text="Output:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        self.entry_output = ttk.Entry(output_frame, textvariable=self.output_var)
        self.entry_output.grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=2)

        self.btn_browse_out = ttk.Button(output_frame, text="Pilih Folder...", command=self._browse_output_dir)
        self.btn_browse_out.grid(row=0, column=2, pady=2)

        lbl_hint = ttk.Label(
            output_frame,
            text="(Kosongkan untuk simpan di folder yang sama dengan input)",
            font=("Segoe UI", 8, "italic"),
            foreground="#555555"
        )
        lbl_hint.grid(row=1, column=1, sticky="w", padx=(0, 6), pady=(2, 0))

        # ---------------- 3. Frame Pengaturan ----------------
        settings_frame = ttk.LabelFrame(main_frame, text="Pengaturan Konversi", padding=8)
        settings_frame.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(3, weight=1)

        # Baris 0: Kualitas & Resolusi
        ttk.Label(settings_frame, text="Kualitas:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        self.cb_quality = ttk.Combobox(
            settings_frame,
            textvariable=self.quality_var,
            values=["max", "medium"],
            state="readonly",
            width=12
        )
        self.cb_quality.grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=3)

        ttk.Label(settings_frame, text="Resolusi:").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=3)
        self.cb_scale = ttk.Combobox(
            settings_frame,
            textvariable=self.scale_var,
            values=["original", "1080p", "720p", "480p"],
            state="readonly",
            width=12
        )
        self.cb_scale.grid(row=0, column=3, sticky="ew", pady=3)

        # Baris 1: Mode & GPU
        ttk.Label(settings_frame, text="Mode:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=3)
        self.cb_mode = ttk.Combobox(
            settings_frame,
            textvariable=self.mode_var,
            values=["auto", "copy", "reencode"],
            state="readonly",
            width=12
        )
        self.cb_mode.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=3)

        ttk.Label(settings_frame, text="GPU:").grid(row=1, column=2, sticky="w", padx=(0, 6), pady=3)
        self.cb_gpu = ttk.Combobox(
            settings_frame,
            textvariable=self.gpu_var,
            values=["auto", "none", "nvenc", "qsv", "amf"],
            state="readonly",
            width=12
        )
        self.cb_gpu.grid(row=1, column=3, sticky="ew", pady=3)

        # Baris 2: Checkboxes
        chk_frame = ttk.Frame(settings_frame)
        chk_frame.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        self.chk_recursive = ttk.Checkbutton(
            chk_frame, text="Rekursif subfolder (-r)", variable=self.recursive_var
        )
        self.chk_recursive.pack(side=tk.LEFT, padx=(0, 14))

        self.chk_force = ttk.Checkbutton(
            chk_frame, text="Timpa file jika sudah ada (-f)", variable=self.force_var
        )
        self.chk_force.pack(side=tk.LEFT, padx=(0, 14))

        self.chk_accurate = ttk.Checkbutton(
            chk_frame, text="Estimasi akurat (sampling) (--accurate)", variable=self.accurate_var
        )
        self.chk_accurate.pack(side=tk.LEFT)

        # ---------------- 4. Frame Action ----------------
        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=3, column=0, sticky="ew", pady=(2, 6))

        self.btn_estimate = ttk.Button(action_frame, text="Estimasi Ukuran", command=self._on_estimate_clicked)
        self.btn_estimate.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_convert = ttk.Button(action_frame, text="Mulai Konversi", command=self._on_convert_clicked)
        self.btn_convert.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_cancel = ttk.Button(action_frame, text="Batal / Stop", command=self._on_cancel_clicked, state=tk.DISABLED)
        self.btn_cancel.pack(side=tk.LEFT)

        # ---------------- 5. Frame Progress & Status ----------------
        progress_frame = ttk.LabelFrame(main_frame, text="Status & Progress", padding=8)
        progress_frame.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        progress_frame.columnconfigure(0, weight=1)
        progress_frame.columnconfigure(1, weight=1)

        self.lbl_status = ttk.Label(progress_frame, textvariable=self.status_var, font=("Segoe UI", 9, "bold"))
        self.lbl_status.grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.lbl_progress_info = ttk.Label(progress_frame, textvariable=self.progress_info_var, font=("Segoe UI", 9))
        self.lbl_progress_info.grid(row=0, column=1, sticky="e", pady=(0, 4))

        self.progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", maximum=100)
        self.progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew")

        # ---------------- 6. Frame Log ----------------
        log_frame = ttk.LabelFrame(main_frame, text="Log Aktivitas", padding=8)
        log_frame.grid(row=5, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            height=9,
            font=("Consolas", 9),
            state="disabled",
            bg="#fdfdfd"
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

    # -------------------------------------------------------------
    # Helper Log & File Browse
    # -------------------------------------------------------------
    def _append_log(self, text: str):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def _check_dependencies(self):
        if not FFMPEG or not FFPROBE:
            self._append_log("[!] PERINGATAN: FFmpeg / FFprobe tidak ditemukan di PATH sistem!")
            self._append_log("    Silakan instal FFmpeg (misal: winget install Gyan.FFmpeg) agar aplikasi dapat bekerja.\n")
        else:
            self._append_log(f"[*] FFmpeg terdeteksi : {FFMPEG}")
            self._append_log(f"[*] FFprobe terdeteksi: {FFPROBE}\n")

    def _browse_input_file(self):
        f = filedialog.askopenfilename(
            title="Pilih File Video .MOV",
            filetypes=[("QuickTime Movie (*.mov)", "*.mov;*.MOV"), ("Semua File", "*.*")]
        )
        if f:
            self.input_var.set(os.path.normpath(f))

    def _browse_input_dir(self):
        d = filedialog.askdirectory(title="Pilih Folder Berisi File .MOV")
        if d:
            self.input_var.set(os.path.normpath(d))

    def _browse_output_dir(self):
        d = filedialog.askdirectory(title="Pilih Folder Output")
        if d:
            self.output_var.set(os.path.normpath(d))

    def _set_ui_state(self, running: bool):
        self.is_running = running
        st = tk.DISABLED if running else tk.NORMAL
        cancel_st = tk.NORMAL if running else tk.DISABLED

        self.btn_convert.config(state=st)
        self.btn_estimate.config(state=st)
        self.btn_browse_in_file.config(state=st)
        self.btn_browse_in_dir.config(state=st)
        self.btn_browse_out.config(state=st)
        self.btn_cancel.config(state=cancel_st)

        self.cb_quality.config(state=st if not running else "disabled")
        self.cb_scale.config(state=st if not running else "disabled")
        self.cb_mode.config(state=st if not running else "disabled")
        self.cb_gpu.config(state=st if not running else "disabled")

    # -------------------------------------------------------------
    # Antrean Thread-Safe (queue.Queue)
    # -------------------------------------------------------------
    def _process_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                mtype = msg[0]
                if mtype == "log":
                    self._append_log(msg[1])
                elif mtype == "status":
                    self.status_var.set(msg[1])
                elif mtype == "progress":
                    pct, eta_str = msg[1], msg[2]
                    self.progress_bar["value"] = pct
                    self.progress_info_var.set(eta_str)
                elif mtype == "finish":
                    self._set_ui_state(False)
        except queue.Empty:
            pass

        self.root.after(50, self._process_queue)

    # -------------------------------------------------------------
    # Validasi Input
    # -------------------------------------------------------------
    def _validate_inputs(self):
        if not FFMPEG or not FFPROBE:
            msg = (
                "FFmpeg atau FFprobe tidak ditemukan di PATH sistem!\n\n"
                "Silakan install FFmpeg terlebih dahulu (misal: 'winget install Gyan.FFmpeg') "
                "dan pastikan ffmpeg/ffprobe dapat diakses dari PATH."
            )
            messagebox.showerror("FFmpeg Tidak Ditemukan", msg)
            self._append_log("[!] " + msg)
            return None, None, None

        src_str = self.input_var.get().strip()
        if not src_str:
            messagebox.showwarning("Input Kosong", "Silakan pilih file .mov atau folder input terlebih dahulu.")
            return None, None, None

        src = Path(src_str).expanduser()
        if not src.exists():
            messagebox.showerror("Path Tidak Ditemukan", f"File atau folder input tidak ditemukan:\n{src}")
            return None, None, None

        out_str = self.output_var.get().strip()
        out_arg = Path(out_str).expanduser() if out_str else None

        if out_arg and src.is_dir() and out_arg.suffix.lower() == ".mp4":
            messagebox.showerror(
                "Format Output Salah",
                "Untuk input berupa folder, folder output harus berupa folder, bukan file .mp4."
            )
            return None, None, None

        recursive = self.recursive_var.get()
        files = collect(src, recursive)
        if not files:
            msg = "Tidak ada file .mov yang ditemukan pada sumber yang dipilih."
            if not recursive and src.is_dir():
                msg += "\n(Coba centang opsi 'Rekursif subfolder (-r)')"
            messagebox.showinfo("Tidak Ada File", msg)
            self._append_log("[i] " + msg)
            return None, None, None

        return src, out_arg, files

    def _dst_for(self, src: Path, out_arg: Path, f: Path) -> Path:
        if src.is_file() or src == f:
            if out_arg and out_arg.suffix.lower() == ".mp4":
                return out_arg
            if out_arg:
                return out_arg / (f.stem + ".mp4")
            return f.with_suffix(".mp4")
        rel = f.relative_to(src).with_suffix(".mp4")
        return (out_arg or src) / rel

    # -------------------------------------------------------------
    # Aksi: Estimasi Ukuran
    # -------------------------------------------------------------
    def _on_estimate_clicked(self):
        if self.is_running:
            return

        src, out_arg, files = self._validate_inputs()
        if not files:
            return

        quality = self.quality_var.get()
        prof = PROFILES.get(quality, PROFILES["max"])
        scale_key = self.scale_var.get()
        mode = self.mode_var.get()
        gpu_choice = self.gpu_var.get()
        accurate = self.accurate_var.get()

        self.cancel_event.clear()
        self._set_ui_state(True)
        self.progress_bar["value"] = 0
        self.progress_info_var.set("0.0% | Estimasi...")
        self.status_var.set(f"Menghitung estimasi ({len(files)} file)...")

        self.worker_thread = threading.Thread(
            target=self._worker_estimate,
            args=(files, prof, scale_key, mode, gpu_choice, accurate),
            daemon=True
        )
        self.worker_thread.start()

    def _worker_estimate(self, files, prof, scale_key, mode, gpu_choice, accurate):
        total_files = len(files)
        gpu = resolve_gpu(gpu_choice)

        self.queue.put(("log", f"--- MULAI ESTIMASI ({total_files} file) ---"))
        self.queue.put(("log", f"Profil: {prof['label']} | Mode: {mode} | Resolusi: {scale_key} | GPU: {gpu}"))

        total_orig = 0
        total_low = 0
        total_mid = 0
        total_high = 0

        for idx, f in enumerate(files, 1):
            if self.cancel_event.is_set():
                self.queue.put(("log", "[!] Proses estimasi dibatalkan."))
                break

            self.queue.put(("status", f"Memeriksa file [{idx}/{total_files}]: {f.name}"))
            pct = (idx - 1) / total_files * 100
            self.queue.put(("progress", pct, f"{idx}/{total_files} file"))
            self.queue.put(("log", f"\n[{idx}/{total_files}] {f}"))

            try:
                info = probe(f)
                out_w, out_h, scaled = target_size(info, scale_key)
                vcopy, acopy, warn = make_plan(info, mode, scaled)
                low, mid, high = estimate(info, prof, vcopy, acopy, out_w, out_h)

                total_orig += info.size
                total_low += low
                total_mid += mid
                total_high += high

                self.queue.put(("log", f"  Ukuran asli : {fmt_size(info.size)} ({fmt_dur(info.duration)}, {info.width}x{info.height})"))
                if vcopy:
                    self.queue.put(("log", f"  Estimasi    : ~{fmt_size(mid)} (remux/copy, ukuran hampir sama)"))
                else:
                    self.queue.put(("log", f"  Estimasi    : {fmt_size(low)} - {fmt_size(high)} (tengah ~{fmt_size(mid)})"))

                if warn:
                    self.queue.put(("log", f"  Catatan     : {warn}"))

                if accurate:
                    if self.cancel_event.is_set():
                        break
                    self.queue.put(("log", "  Menghitung estimasi akurat (sampling 3 klip)..."))
                    s = sample_estimate(info, prof, acopy, scale_key, gpu)
                    if s:
                        self.queue.put(("log", f"  Sampling    : ~{fmt_size(s)} (+/- 15%)"))
                    else:
                        self.queue.put(("log", "  Sampling    : Video terlalu pendek atau gagal sampling"))
            except Exception as e:
                self.queue.put(("log", f"  [!] Gagal membaca video: {e}"))

        if not self.cancel_event.is_set():
            self.queue.put(("progress", 100.0, "100% Selesai"))
            self.queue.put(("status", "Estimasi selesai"))
            self.queue.put(("log", "\n=== Total Estimasi Keseluruhan ==="))
            self.queue.put(("log", f"Ukuran Asli Total: {fmt_size(total_orig)}"))
            self.queue.put(("log", f"Estimasi Total   : {fmt_size(total_low)} - {fmt_size(total_high)} (tengah ~{fmt_size(total_mid)})\n"))
        else:
            self.queue.put(("status", "Dibatalkan"))

        self.queue.put(("finish",))

    # -------------------------------------------------------------
    # Aksi: Mulai Konversi
    # -------------------------------------------------------------
    def _on_convert_clicked(self):
        if self.is_running:
            return

        src, out_arg, files = self._validate_inputs()
        if not files:
            return

        quality = self.quality_var.get()
        prof = PROFILES.get(quality, PROFILES["max"])
        scale_key = self.scale_var.get()
        mode = self.mode_var.get()
        gpu_choice = self.gpu_var.get()
        force = self.force_var.get()
        accurate = self.accurate_var.get()

        self.cancel_event.clear()
        self._set_ui_state(True)
        self.progress_bar["value"] = 0
        self.progress_info_var.set("0.0% | Menyiapkan...")
        self.status_var.set(f"Memulai konversi ({len(files)} file)...")

        self.worker_thread = threading.Thread(
            target=self._worker_convert,
            args=(files, src, out_arg, prof, scale_key, mode, gpu_choice, force, accurate),
            daemon=True
        )
        self.worker_thread.start()

    def _worker_convert(self, files, src, out_arg, prof, scale_key, mode, gpu_choice, force, accurate):
        total_files = len(files)
        gpu = resolve_gpu(gpu_choice)

        self.queue.put(("log", f"--- MEMULAI KONVERSI ({total_files} file) ---"))
        enc_label = {"nvenc": "NVIDIA NVENC", "qsv": "Intel QSV", "amf": "AMD AMF"}.get(gpu, "CPU (libx264)")
        self.queue.put(("log", f"Profil: {prof['label']} | Mode: {mode} | Resolusi: {scale_key} | Encoder: {enc_label}"))

        stats = {"done": 0, "skipped": 0, "failed": 0}
        total_in = 0
        total_out = 0

        for idx, f in enumerate(files, 1):
            if self.cancel_event.is_set():
                self.queue.put(("log", "\n[!] Konversi dihentikan oleh pengguna."))
                break

            self.queue.put(("status", f"Memproses [{idx}/{total_files}]: {f.name}"))
            self.queue.put(("progress", 0.0, f"[{idx}/{total_files}] 0.0%"))
            self.queue.put(("log", f"\n[{idx}/{total_files}] {f}"))

            dst = self._dst_for(src, out_arg, f)

            try:
                info = probe(f)
                out_w, out_h, scaled = target_size(info, scale_key)
                vcopy, acopy, warn = make_plan(info, mode, scaled)

                how = ("remux (tanpa re-encode)" if vcopy and acopy else
                       "video di-copy, audio -> AAC" if vcopy else
                       f"re-encode H.264 via {enc_label}" if gpu != "none" else
                       f"re-encode H.264 CRF {prof['crf']} / preset {prof['preset']} (CPU)")

                self.queue.put(("log", f"  Detail  : {info.width}x{info.height} @ {info.fps:.2f}fps, {fmt_dur(info.duration)}, {info.vcodec}"))
                self.queue.put(("log", f"  Metode  : {how}"))
                if scaled:
                    self.queue.put(("log", f"  Resolusi: {info.dw}x{info.dh} -> {out_w}x{out_h} ({scale_key})"))
                elif SCALES.get(scale_key):
                    self.queue.put(("log", f"  Resolusi: {info.dw}x{info.dh} sudah <= {scale_key}, tidak diubah"))
                if warn:
                    self.queue.put(("log", f"  Catatan : {warn}"))
                if info.skipped_audio:
                    self.queue.put(("log", f"  Audio   : Track {','.join(info.skipped_audio)} dilewati (tidak kompatibel)"))

                # Cek jika file tujuan sudah ada
                if dst.exists() and not force:
                    self.queue.put(("log", f"  SKIP    : {dst.name} sudah ada (gunakan -f / centang timpa file)"))
                    stats["skipped"] += 1
                    self.queue.put(("progress", 100.0, f"[{idx}/{total_files}] Lewati"))
                    continue

                if accurate and not vcopy:
                    if self.cancel_event.is_set():
                        break
                    s = sample_estimate(info, prof, acopy, scale_key, gpu)
                    if s:
                        self.queue.put(("log", f"  Estimasi: ~{fmt_size(s)}"))

                # Buat direktori tujuan jika belum ada
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_name(dst.stem + f".part{threading.get_ident()}.mp4")
                self.current_tmp = tmp

                cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(f), "-map", "0:v:0"]
                for a_idx in info.audio_idx:
                    cmd += ["-map", f"0:{a_idx}"]
                cmd += ["-sn", "-dn", "-map_metadata", "0"]
                cmd += ["-c:v", "copy"] if vcopy else video_args(prof, scale_key, gpu)
                cmd += ["-c:a", "copy"] if acopy else ["-c:a", "aac", "-b:a", f"{prof['abr']}k"]
                cmd += ["-movflags", "+faststart", str(tmp)]

                full_cmd = cmd + ["-progress", "pipe:1", "-nostats"]

                creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                proc = subprocess.Popen(
                    full_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creationflags
                )
                self.current_proc = proc

                errors = []
                start_time = time.time()

                try:
                    for line in proc.stdout:
                        if self.cancel_event.is_set():
                            try:
                                proc.kill()
                            except Exception:
                                pass
                            break

                        line = line.strip()
                        if line.startswith("out_time_us="):
                            try:
                                done_sec = int(line.split("=", 1)[1]) / 1_000_000
                                if info.duration > 0:
                                    pct = min(100.0, done_sec / info.duration * 100)
                                    elapsed = time.time() - start_time
                                    eta_sec = (elapsed / pct * (100 - pct)) if pct > 1 else 0
                                    eta_str = fmt_dur(eta_sec)
                                    self.queue.put(("progress", pct, f"[{idx}/{total_files}] {pct:.1f}% | Sisa ~{eta_str}"))
                            except (ValueError, ZeroDivisionError):
                                pass
                        elif "=" not in line and line:
                            errors.append(line)
                except Exception:
                    pass

                try:
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

                self.current_proc = None

                if self.cancel_event.is_set():
                    if tmp.exists():
                        tmp.unlink(missing_ok=True)
                    self.current_tmp = None
                    break

                if proc.returncode != 0:
                    if tmp.exists():
                        tmp.unlink(missing_ok=True)
                    self.current_tmp = None
                    err_text = "\n    ".join(errors[-10:]) if errors else f"Exit code {proc.returncode}"
                    raise RuntimeError(f"FFmpeg gagal:\n    {err_text}")

                # Berhasil konversi: pindahkan temporary file ke file tujuan akhir
                os.replace(tmp, dst)
                self.current_tmp = None

                out_size = dst.stat().st_size
                ratio = (out_size / info.size * 100) if info.size else 0
                self.queue.put(("log", f"  Selesai : {dst.name} ({fmt_size(out_size)}, {ratio:.0f}% dari asli)"))
                self.queue.put(("progress", 100.0, f"[{idx}/{total_files}] Selesai (100%)"))

                stats["done"] += 1
                total_in += info.size
                total_out += out_size

            except Exception as e:
                if self.current_tmp and self.current_tmp.exists():
                    try:
                        self.current_tmp.unlink(missing_ok=True)
                    except Exception:
                        pass
                self.current_tmp = None
                stats["failed"] += 1
                self.queue.put(("log", f"  [!] GAGAL: {e}"))

        # Ringkasan hasil
        if self.cancel_event.is_set():
            self.queue.put(("status", "Proses dibatalkan"))
            self.queue.put(("log", "\n=== Proses Dibatalkan ==="))
        else:
            self.queue.put(("status", "Semua file selesai dikonversi"))
            self.queue.put(("log", "\n=== Ringkasan Konversi ==="))

        self.queue.put(("log", f"Selesai: {stats['done']} | Skip: {stats['skipped']} | Gagal: {stats['failed']}"))
        if stats["done"]:
            total_ratio = (total_out / total_in * 100) if total_in else 0
            saved = total_in - total_out
            self.queue.put((
                "log",
                f"Ukuran total: {fmt_size(total_in)} -> {fmt_size(total_out)} "
                f"(Rasio: {total_ratio:.1f}%, Penghematan: {fmt_size(saved)})\n"
            ))

        self.queue.put(("finish",))

    # -------------------------------------------------------------
    # Aksi: Batal / Stop
    # -------------------------------------------------------------
    def _on_cancel_clicked(self):
        if not self.is_running:
            return

        self.btn_cancel.config(state=tk.DISABLED)
        self.cancel_event.set()
        self.status_var.set("Membatalkan proses...")
        self.progress_info_var.set("Membatalkan...")
        self._append_log("\n[!] Pembatalan diminta oleh pengguna. Menghentikan proses...")

        if self.current_proc and self.current_proc.poll() is None:
            try:
                self.current_proc.kill()
            except Exception:
                pass

        if self.current_tmp and self.current_tmp.exists():
            try:
                self.current_tmp.unlink(missing_ok=True)
            except Exception:
                pass

    # -------------------------------------------------------------
    # Window Close Handler
    # -------------------------------------------------------------
    def _on_closing(self):
        if self.is_running:
            if not messagebox.askyesno(
                "Konfirmasi Keluar",
                "Proses sedang berjalan.\nApakah Anda yakin ingin membatalkan dan keluar?"
            ):
                return

            self.cancel_event.set()
            if self.current_proc and self.current_proc.poll() is None:
                try:
                    self.current_proc.kill()
                except Exception:
                    pass

            if self.current_tmp and self.current_tmp.exists():
                try:
                    self.current_tmp.unlink(missing_ok=True)
                except Exception:
                    pass

        self.root.destroy()


def main():
    root = tk.Tk()
    app = Mov2Mp4GUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
