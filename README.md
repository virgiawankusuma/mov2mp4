# mov2mp4

Converter `.mov` ke `.mp4` lewat command line, satu file atau batch satu folder. Dibuat dengan Python dan memanfaatkan [ffmpeg](https://ffmpeg.org/) di balik layar.

## Fitur

- **File satuan atau batch folder**, termasuk subfolder (`-r`).
- **Otomatis pilih metode**: kalau video sudah H.264 (umum dari kamera/iPhone lama), cuma ganti container tanpa re-encode, jadi instan dan kualitas utuh. Kalau codec-nya lain (HEVC, ProRes, dll), di-encode ulang ke H.264.
- **Dua profil kualitas**: `max` (kualitas maksimal) dan `medium` (file lebih kecil).
- **Turunkan resolusi**: 1080p, 720p, atau 480p, dengan rasio asli terjaga dan tanpa upscale.
- **Encode pakai GPU** (NVIDIA/Intel/AMD) buat re-encode yang jauh lebih cepat daripada CPU.
- **Konversi paralel**: beberapa file dikerjain bersamaan saat batch folder.
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
python mov2mp4.py video.mov -g auto              # encode pakai GPU kalau ada
python mov2mp4.py video.mov -e                   # cuma estimasi ukuran, tanpa convert
python mov2mp4.py video.mov -e --accurate        # estimasi lebih akurat (encode sampel pendek)
python mov2mp4.py D:\Videos -r -o D:\Hasil       # batch satu folder + subfolder
python mov2mp4.py D:\Videos -r -g auto -j 2      # batch + GPU + 2 file paralel (lebih cepat)
```

### Opsi

| Opsi | Keterangan |
| --- | --- |
| `-o`, `--output` | File `.mp4` tujuan (untuk 1 file) atau folder tujuan. Tanpa opsi ini, hasil disimpan di samping file asli. |
| `-q`, `--quality` | `max` (default) atau `medium`. Lihat tabel profil di bawah. |
| `-s`, `--scale` | `original` (default), `1080p`, `720p`, atau `480p`. |
| `-m`, `--mode` | `auto` (default), `copy`, atau `reencode`. Lihat penjelasan di bawah. |
| `-g`, `--gpu` | `none` (default, CPU/libx264), `auto`, `nvenc`, `qsv`, atau `amf`. Lihat penjelasan di bawah. |
| `-j`, `--jobs` | Jumlah file yang dikonversi bersamaan saat batch folder (default: `1`). |
| `-r`, `--recursive` | Masuk ke subfolder (mode folder). |
| `-f`, `--force` | Timpa file `.mp4` yang sudah ada. Tanpa ini, file yang sudah ada di-skip. |
| `-e`, `--estimate` | Hanya tampilkan estimasi ukuran, tidak mengonversi. |
| `--accurate` | Estimasi lebih akurat dengan meng-encode 3 klip sampel pendek (lebih lama). |

### Profil kualitas

| Profil | Video (CPU) | Audio |
| --- | --- | --- |
| `max` | H.264, CRF 17, preset `slow` | AAC 256 kbps |
| `medium` | H.264, CRF 23, preset `medium` | AAC 160 kbps |

CRF makin kecil berarti kualitas makin tinggi (dan file makin besar). Saat pakai GPU (`-g`), profil yang sama dipetakan ke parameter kualitas setara di encoder GPU-nya (lihat bagian GPU di bawah).

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

### GPU (encode lebih cepat)

Secara default konversi pakai CPU (`libx264`), yang paling kompatibel tapi paling lambat untuk re-encode (HEVC, ProRes, ganti resolusi, dll). Opsi `-g` memakai encoder GPU kalau tersedia:

| Nilai | GPU | Catatan |
| --- | --- | --- |
| `none` | - | CPU/libx264 (default) |
| `auto` | - | Pakai GPU pertama yang terdeteksi dari `ffmpeg` (NVIDIA → Intel → AMD), fallback ke CPU kalau tidak ada |
| `nvenc` | NVIDIA | Perlu GPU NVIDIA + driver yang mendukung NVENC |
| `qsv` | Intel | Perlu CPU Intel dengan Quick Sync + driver media yang aktif |
| `amf` | AMD | Perlu GPU AMD dengan dukungan AMF |

Kalau encoder yang diminta tidak didukung oleh `ffmpeg` di sistemmu (biasanya karena build `ffmpeg`-nya tidak include encoder itu, atau driver GPU belum terpasang), script otomatis fallback ke CPU dan kasih peringatan. Cek dulu encoder yang tersedia dengan:

```
ffmpeg -encoders | findstr nvenc      # Windows, cek NVIDIA
ffmpeg -hide_banner -encoders | grep nvenc    # macOS/Linux
```

Catatan: GPU tidak dipakai saat mode `copy`/remux murni — GPU cuma berpengaruh saat video memang di-re-encode (codec bukan H.264, ganti resolusi, atau mode `reencode`).

### Konversi paralel (`-j`)

Saat batch folder, `-j N` mengonversi N file sekaligus alih-alih satu per satu. Beberapa catatan:

- Dengan `-g` (GPU): umumnya aman naikkan ke `2`-`3`, karena GPU jadi bottleneck, bukan CPU.
- Tanpa `-g` (CPU/libx264): `-j` tinggi bisa membuat tiap file malah lebih lambat karena core CPU terbagi; coba `1`-`2` dulu dan lihat hasilnya.
- Progress bar per-frame dimatikan saat `-j` lebih dari 1 (supaya output antar file tidak tabrakan); setiap file tetap melapor statusnya begitu selesai.
- `Ctrl+C` tetap membatalkan semua proses yang sedang jalan dan membersihkan file sementara.

## Hal yang perlu diketahui

- **Video HDR (HLG / Dolby Vision, 10-bit)**: output selalu 8-bit SDR (`yuv420p`), sehingga warna video HDR bisa terlihat lebih pucat. Belum ada tone mapping.
- **Track audio `apple_apac`** (spatial audio iPhone) otomatis dilewati karena ffmpeg tidak bisa men-decode-nya. Track audio biasa (AAC) tetap dipakai.
- **Hanya satu track video** yang diambil. Subtitle dan data track dibuang.
- **Estimasi ukuran** berupa rentang perkiraan, bukan angka pasti. Untuk hasil lebih dekat, pakai `--accurate`.
- **Kualitas GPU vs CPU**: pada bitrate yang sama, encoder GPU (NVENC/QSV/AMF) umumnya sedikit kalah efisien dibanding `libx264`, artinya file bisa sedikit lebih besar untuk kualitas yang setara. Trade-off-nya kecepatan jauh lebih tinggi.

## Kode keluar (exit code)

| Kode | Arti |
| --- | --- |
| `0` | Semua berhasil |
| `1` | Ada file yang gagal, atau tidak ada file `.mov` ditemukan |
| `2` | ffmpeg tidak ditemukan, atau path input/output tidak valid |
| `130` | Dibatalkan dengan Ctrl+C |
