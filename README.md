# mov2mp4

Converter `.mov` ke `.mp4` lewat command line, satu file atau batch satu folder. Dibuat dengan Python dan memanfaatkan [ffmpeg](https://ffmpeg.org/) di balik layar.

## Fitur

- **File satuan atau batch folder**, termasuk subfolder (`-r`).
- **Otomatis pilih metode**: kalau video sudah H.264 (umum dari kamera/iPhone lama), cuma ganti container tanpa re-encode, jadi instan dan kualitas utuh. Kalau codec-nya lain (HEVC, ProRes, dll), di-encode ulang ke H.264.
- **Dua profil kualitas**: `max` (kualitas maksimal) dan `medium` (file lebih kecil).
- **Turunkan resolusi**: 1080p, 720p, atau 480p, dengan rasio asli terjaga dan tanpa upscale.
- **Estimasi ukuran file** sebelum konversi, dengan mode `--accurate` untuk hasil lebih mendekati kenyataan.
- **Progress bar dan estimasi sisa waktu** per file.
- **Aman**: output ditulis ke file sementara dulu, jadi pembatalan (Ctrl+C) nggak ninggalin `.mp4` setengah jadi. Satu file gagal nggak menghentikan batch.
- **Metadata asli ikut terbawa** (tanggal rekam, dll) dan `faststart` diaktifkan supaya enak di-stream.

## Kebutuhan

- Python 3.8 atau lebih baru (tanpa library tambahan)
- `ffmpeg` dan `ffprobe` yang bisa dipanggil dari PATH

### Install ffmpeg di Windows

Pilih salah satu:

```
winget install Gyan.FFmpeg
choco install ffmpeg
scoop install ffmpeg
```

Tutup dan buka lagi terminalnya, lalu cek dengan `ffmpeg -version`.

### macOS / Linux

```
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Debian/Ubuntu
```

## Cara pakai

```
python mov2mp4.py <input> [opsi]
```

`<input>` bisa berupa file `.mov` atau folder berisi file `.mov`.

### Contoh

```
python mov2mp4.py video.mov                      # kualitas maksimal (default)
python mov2mp4.py video.mov -q medium            # kualitas sedang, file lebih kecil
python mov2mp4.py video.mov -s 1080p             # turunkan ke 1920x1080
python mov2mp4.py video.mov -s 720p -q medium    # 1280x720, kualitas sedang
python mov2mp4.py video.mov -e                   # cuma estimasi ukuran, tanpa convert
python mov2mp4.py video.mov -e --accurate        # estimasi lebih akurat (encode sampel pendek)
python mov2mp4.py D:\Videos -r -o D:\Hasil       # batch satu folder + subfolder
```

### Opsi

| Opsi | Keterangan |
| --- | --- |
| `-o`, `--output` | File `.mp4` tujuan (untuk 1 file) atau folder tujuan. Tanpa opsi ini, hasil disimpan di samping file asli. |
| `-q`, `--quality` | `max` (default) atau `medium`. Lihat tabel profil di bawah. |
| `-s`, `--scale` | `original` (default), `1080p`, `720p`, atau `480p`. |
| `-m`, `--mode` | `auto` (default), `copy`, atau `reencode`. Lihat penjelasan di bawah. |
| `-r`, `--recursive` | Masuk ke subfolder (mode folder). |
| `-f`, `--force` | Timpa file `.mp4` yang sudah ada. Tanpa ini, file yang sudah ada di-skip. |
| `-e`, `--estimate` | Hanya tampilkan estimasi ukuran, tidak mengonversi. |
| `--accurate` | Estimasi lebih akurat dengan meng-encode 3 klip sampel pendek (lebih lama). |

### Profil kualitas

| Profil | Video | Audio |
| --- | --- | --- |
| `max` | H.264, CRF 17, preset `slow` | AAC 256 kbps |
| `medium` | H.264, CRF 23, preset `medium` | AAC 160 kbps |

CRF makin kecil berarti kualitas makin tinggi (dan file makin besar).

### Mode konversi

- `auto`: remux kalau video sudah H.264 8-bit, selain itu re-encode.
- `copy`: paksa remux. Kalau codec-nya tidak cocok, tetap jatuh ke re-encode.
- `reencode`: paksa encode ulang. Berguna kalau ingin profil `medium` benar-benar mengecilkan file yang sudah H.264.

Catatan: kalau video sudah H.264 dan mode `auto`, video cuma di-remux sehingga opsi `-q` tidak berpengaruh ke videonya. Gunakan `-m reencode` kalau ingin tetap di-encode ulang.

### Resolusi

Angka 1080p/720p/480p adalah batas **sisi pendek** video, jadi:

- video landscape 4K dengan `-s 1080p` menjadi 1920x1080
- video portrait 4K dengan `-s 1080p` menjadi 1080x1920

Video yang sudah lebih kecil dari target tidak diubah. Mengganti resolusi selalu butuh re-encode, jadi prosesnya lebih lama daripada remux.

## Hal yang perlu diketahui

- **Video HDR (HLG / Dolby Vision, 10-bit)**: output selalu 8-bit SDR (`yuv420p`), sehingga warna video HDR bisa terlihat lebih pucat. Belum ada tone mapping.
- **Track audio `apple_apac`** (spatial audio iPhone) otomatis dilewati karena ffmpeg tidak bisa men-decode-nya. Track audio biasa (AAC) tetap dipakai.
- **Hanya satu track video** yang diambil. Subtitle dan data track dibuang.
- **Estimasi ukuran** berupa rentang perkiraan, bukan angka pasti. Untuk hasil lebih dekat, pakai `--accurate`.

## Kode keluar (exit code)

| Kode | Arti |
| --- | --- |
| `0` | Semua berhasil |
| `1` | Ada file yang gagal, atau tidak ada file `.mov` ditemukan |
| `2` | ffmpeg tidak ditemukan, atau path input/output tidak valid |
| `130` | Dibatalkan dengan Ctrl+C |
