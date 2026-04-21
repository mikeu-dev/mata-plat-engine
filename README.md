# 🚗 Mata Plat Engine - AI Detection Unit

![Mata Plat Engine Header](https://raw.githubusercontent.com/mikeudev/mata-plat-engine/main/static/engine-banner.png)

> **Mata Plat Engine** adalah unit pemrosesan AI cerdas yang berfungsi sebagai "mata" dari ekosistem Mata Plat. Sistem ini melakukan deteksi kendaraan, pengenalan plat nomor (ALPR), dan analisis aktivitas parkir secara *real-time* dari berbagai sumber video (RTSP/CCTV).

---

## 🌟 Kapabilitas Utama (Core Capabilities)

### 🧠 Advanced AI Detection
- **Vehicle Detection**: Klasifikasi cerdas untuk berbagai jenis kendaraan (Mobil, Motor, Bus, Truk) menggunakan model YOLOv8 yang telah dioptimasi.
- **Automatic License Plate Recognition (ALPR)**: Ekstraksi teks plat nomor secara presisi menggunakan PaddleOCR.
- **Direction & Movement Analysis**: State machine untuk mendeteksi apakah kendaraan masuk, keluar, atau sedang terparkir.

### 🔒 Enterprise Security Implementation
- **Hardware ID (HWID) Validation**: Memastikan hanya perangkat fisik yang terdaftar yang dapat beroperasi dan mengirim data.
- **HMAC Webhook Signing**: Setiap event yang dikirim ke dashboard pusat ditandatangani secara kriptografis untuk mencegah *request tampering*.
- **API Key Protection**: Seluruh endpoint API dilindungi dengan enkripsi x-api-key yang unik untuk setiap node.

### 📡 High-Performance Streaming
- **MJPEG/RTSP Proxy**: Menyediakan stream video yang efisien untuk dipantau langsung di Command Center.
- **Real-time Heartbeat**: Mengirim status kesehatan sistem secara berkala ke dashboard pusat untuk monitoring reliabilitas.

---

## 🛠️ Tech Stack

- **AI Framework**: Python 3.10+, OpenCV, Ultralytics YOLOv8, PaddleOCR.
- **Backend API**: Flask (Lightweight & Fast).
- **Security**: HMAC-SHA256, HWID Binding.
- **Monitoring**: Streamlit (Internal Debugging Dashboard).
- **Environment**: Python Virtual Environment (venv).

---

## 🚀 Panduan Instalasi & Setup

### 1. Prasyarat Sistem
- Python 3.8 - 3.11
- NVIDIA GPU dengan CUDA (Sangat disarankan untuk produksi)
- Library Sistem: `libgl1-mesa-glx`, `libglib2.0-0`

### 2. Persiapan Environment
```bash
# Clone repositori
git clone https://github.com/username/mata-plat-engine.git
cd mata-plat-engine

# Setup Virtual Environment
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalasi Dependensi
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Konfigurasi Environment (.env)
Salin template dan sesuaikan variabel kunci:
```bash
cp .env.example .env
```
Variabel krusial yang harus diatur:
- `MAIN_DASHBOARD_URL`: URL pusat dashboard Mata Plat.
- `ENGINE_API_KEY`: Key unik untuk otentikasi engine.
- `RTSP_URL`: Sumber stream kamera CCTV.

---

## 🖥️ Cara Menjalankan

### Mode Produksi (Background Service)
Disarankan menggunakan PM2 untuk memastikan engine tetap berjalan setelah restart:
```bash
pm2 start engine_parkir.py --name "mata-plat-engine" --interpreter ./venv/bin/python
```

### Mode Pengembangan & Debugging
```bash
# Menjalankan AI Engine Utama
python engine_parkir.py

# Menjalankan Dashboard Monitor Lokal (Streamlit)
streamlit run dashboard_parkir.py
```

---

## 🛡️ Dokumentasi API & Integrasi

Setiap engine menyediakan endpoint lokal untuk monitoring:
- **Health Check**: `GET /api/v1/health`
- **Video Feed**: `GET /video_feed?api_key=SECRET`
- **Configuration**: `POST /api/v1/config` (Dilindungi HMAC)

---

## 📝 Troubleshooting

- **GPU Tidak Terdeteksi**: Pastikan `torch.cuda.is_available()` bernilai `True`. Jika menggunakan CPU, pastikan parameter `.to("cpu")` sudah diset di config.
- **Gagal Validasi HWID**: Pastikan file `.hwid` di direktori root sesuai dengan yang terdaftar di Dashboard Pusat.

---

Dibuat dengan ❤️ oleh **Tim Mata Plat**. 🚀
