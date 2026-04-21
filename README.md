# 🚗 Smart Parking AI Dashboard (Mata Plat Engine)

Sistem AI cerdas untuk manajemen parkir otomatis yang mampu mendeteksi kendaraan, mengenali plat nomor (ALPR), dan menghitung biaya parkir secara *real-time* menggunakan video stream (RTSP).

## 🌟 Fitur Utama
- **Deteksi Kendaraan**: Mendeteksi berbagai jenis kendaraan (mobil, motor, bus, truk) menggunakan YOLOv8.
- **Automatic License Plate Recognition (ALPR)**: Membaca plat nomor kendaraan secara otomatis menggunakan PaddleOCR.
- **State Machine Detection**: Menentukan apakah kendaraan sedang bergerak atau berhenti (parkir) berdasarkan koordinat posisi.
- **Sistem Billing Otomatis**: Menghitung lama parkir dan total biaya secara otomatis saat kendaraan keluar.
- **Dual Dashboard**: Tersedia dashboard berbasis **Flask** (sederhana) dan **Streamlit** (modern dengan visualisasi data).

## 🛠️ Tech Stack
- **AI Engine**: Python, OpenCV, YOLOv8 (Ultralytics), PaddleOCR.
- **Backend**: Flask.
- **Dashboard**: Streamlit, Pandas, SQLAlchemy.
- **Database**: MySQL.
- **Environment**: Python Virtual Environment (venv), Dotenv.

## 🚀 Panduan Instalasi

### 1. Prasyarat
- Python 3.8 ke atas.
- MySQL Server (misal: XAMPP).
- NVIDIA GPU (disarankan untuk performa maksimal dengan CUDA).

### 2. Kloning Repositori
```bash
git clone https://github.com/username/mata-plat-engine.git
cd mata-plat-engine
```

### 3. Setup Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate  # Untuk Linux/Mac
# venv\Scripts\activate   # Untuk Windows
```

### 4. Instalasi Dependensi
```bash
pip install -r requirements.txt
```

### 5. Konfigurasi Database
Buat database di MySQL dengan nama `parking_db` dan jalankan perintah SQL berikut:
```sql
CREATE TABLE IF NOT EXISTS logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    plate VARCHAR(20),
    time_in DATETIME DEFAULT CURRENT_TIMESTAMP,
    time_out DATETIME,
    total_bill INT DEFAULT 0,
    vehicle_type VARCHAR(50)
);
```

### 6. Konfigurasi Environment (.env)
Salin file template `.env.example` menjadi `.env` dan sesuaikan nilainya:
```bash
cp .env.example .env
```
Sesuaikan `DB_PASS` dan `RTSP_URL` (URL CCTV Anda) di dalam file `.env`.

## 🖥️ Cara Menjalankan

### Menjalankan Engine Deteksi
Engine ini wajib dijalankan agar sistem dapat memproses video dan menyimpan data ke database.
```bash
python engine_parkir.py
```

### Menjalankan Dashboard
Anda bisa memilih salah satu dashboard:

**Opsi 1: Streamlit Dashboard (Visualisasi Lengkap)**
```bash
streamlit run dashboard_parkir.py
```

**Opsi 2: Flask Dashboard (Web Sederhana)**
```bash
## 🔒 API Documentation & Security
Engine ini menyediakan API berbasis Flask untuk kebutuhan monitoring dan log:
- **Swagger UI**: Akses `http://localhost:5000/api/v1/docs` untuk dokumentasi interaktif.
- **Security**: Seluruh endpoint dilindungi oleh `x-api-key`. 
- **Integrasi Dashboard**: Pastikan `ENGINE_API_KEY` di engine sama dengan `PUBLIC_ENGINE_API_KEY` di Dashboard GUI.

### Autentikasi
Untuk mengakses API via tool seperti Postman atau cURL:
- Tambahkan header `x-api-key: your-secret-key`
- Khusus untuk `/video_feed`, Anda bisa menggunakan query parameter: `?api_key=your-secret-key`

## 📝 Lisensi
Proyek ini dikembangkan untuk keperluan manajemen parkir berbasis AI.

---
**Catatan**: Untuk menjalankan engine pada mode CPU (jika tidak ada GPU), ubah baris `.to("cuda")` menjadi `.to("cpu")` pada file `engine_parkir.py`.
