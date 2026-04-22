import os
import sys
import cv2
import numpy as np
import time
import threading
import re
import requests
import json
import argparse
from queue import Queue
from ultralytics import YOLO
from paddleocr import PaddleOCR
from dotenv import load_dotenv
import torch
import hashlib
import hmac

load_dotenv()

# Setup CLI Arguments
parser = argparse.ArgumentParser(description='Mata Plat Engine - AI Parking System')
args = parser.parse_args()

# =============================
# SUPPRESS FFMPEG DECODER WARNINGS
# =============================
# FFmpeg (bundled dalam OpenCV) menulis warning HEVC/H.264 langsung ke
# C-level stderr (fd 2). Kita redirect fd 2 ke /dev/null, tapi simpan
# salinan fd asli agar Python sys.stderr tetap berfungsi untuk traceback.
_original_stderr_fd = os.dup(2)
_devnull_fd = os.open(os.devnull, os.O_WRONLY)
os.dup2(_devnull_fd, 2)
os.close(_devnull_fd)
sys.stderr = os.fdopen(_original_stderr_fd, 'w', closefd=False)
print("✅ FFmpeg stderr dialihkan ke /dev/null (warnings disembunyikan)")

# Optimasi RTSP: TCP transport + probe settings + discard corrupt frames
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|"
    "analyzeduration;5000000|"
    "probesize;5000000|"
    "fflags;+discardcorrupt"
)
print("📡 RTSP Transport: TCP (stabilitas optimal)")

# DETEKSI DEVICE (GPU/CPU)
FORCE_DEVICE = os.getenv("AI_DEVICE", "auto").lower()
if FORCE_DEVICE == "auto":
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
else:
    DEVICE = FORCE_DEVICE

DEBUG_MODE = os.getenv("DEBUG_MODE", "False") == "True"
print(f"🚀 Konfigurasi Hardware: {FORCE_DEVICE.upper()}")
print(f"🔧 Menggunakan Device: {DEVICE}")
print(f"🛠️ Debug Mode: {'AKTIF' if DEBUG_MODE else 'NON-AKTIF'}")

# =============================
# GLOBAL MODLES (Model Sharing for Scalability)
# =============================
print("📦 Memuat AI Models ke Memori (Shared Instance)...")
model_vehicle = YOLO("yolov8n.pt")
model_plate = YOLO("license_plate_detector.pt")

try:
    model_vehicle.to(DEVICE)
    model_plate.to(DEVICE)
except Exception as e:
    if "cuda" in DEVICE.lower():
        print(f"⚠️ Gagal menggunakan GPU ({DEVICE}): {str(e)}")
        print("🔄 Fallback otomatis ke CPU...")
        DEVICE = "cpu"
        model_vehicle.to(DEVICE)
        model_plate.to(DEVICE)
    else:
        raise e

# =============================

BIAYA_PER_JAM = int(os.getenv("BIAYA_PER_JAM", 5000))
CLEANUP_INTERVAL = 300 # Bersihkan data setiap 5 menit
IDLE_TIMEOUT = 600    # Hapus tracker yang tidak terlihat selama 10 menit

# =============================
# KONFIGURASI (Default — dapat di-override dari Dashboard)
# =============================

FRAME_SKIP = 2
STOP_DISTANCE = 25
MOVE_DISTANCE = 35
STOP_CONFIRM_FRAMES = 2
MOVE_CONFIRM_FRAMES = 5
VEHICLE_CLASSES = [2,3,5,7]
PLATE_REGEX = r'^[A-Z]{1,2}[0-9]{1,4}[A-Z]{1,3}$'

# Global OCR stays centralized via queue
OCR_USE_GPU = os.getenv("OCR_USE_GPU", "False").lower() == "true"
print(f"🔍 OCR GPU: {'AKTIF' if OCR_USE_GPU else 'NON-AKTIF'}")

try:
    ocr = PaddleOCR(lang="en", use_gpu=OCR_USE_GPU, show_log=False)
except Exception as e:
    if OCR_USE_GPU:
        print(f"⚠️ PaddleOCR gagal menggunakan GPU: {str(e)}")
        print("🔄 Fallback OCR ke CPU...")
        ocr = PaddleOCR(lang="en", use_gpu=False, show_log=False)
    else:
        raise e

# =============================
# ASYNC CAMERA
# =============================

import subprocess
import numpy as np

class VideoCaptureAsync:
    """Async camera capture yang mendukung RTSP dan HLS streams.
    
    - RTSP (rtsp://): Menggunakan cv2.VideoCapture langsung
    - HLS (http/https m3u8): Menggunakan ffmpeg subprocess pipe
      karena OpenCV tidak bisa forward API key ke HLS segment requests.
    """
    def __init__(self, src, gate_id, stop_event=None):
        self.src = src
        self.gate_id = gate_id
        self.cap = None
        self._ffmpeg_proc = None
        self._is_hls = src.startswith('http://') or src.startswith('https://')
        self.ret = False
        self.frame = None
        self.stop_event = stop_event or threading.Event()
        self.connected = False
        self._frame_width = 0
        self._frame_height = 0

        if self._is_hls:
            self._init_hls()
        else:
            self._init_rtsp()

    def _init_hls(self):
        """Inisialisasi HLS stream via Python fetcher + ffmpeg pipe."""
        max_retries = 5
        for i in range(max_retries):
            if self.stop_event.is_set():
                self._safe_release()
                return

            print(f"📡 Mencoba menghubungkan ke HLS stream ({i+1}/{max_retries})...")
            self._kill_ffmpeg()

            # Start ffmpeg subprocess dengan input dari PIPE (stdin)
            # Kita set resolusi manual 960x540 untuk HLS Purwakarta
            self._frame_width = 960
            self._frame_height = 540
            
            ffmpeg_cmd = [
                'ffmpeg',
                '-i', 'pipe:0',           # Ambil input dari stdin
                '-f', 'rawvideo',
                '-pix_fmt', 'bgr24',
                '-vsync', '0',
                '-an', '-sn',
                '-v', 'error',
                'pipe:1'                  # Output frame ke stdout
            ]
            try:
                self._ffmpeg_proc = subprocess.Popen(
                    ffmpeg_cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=self._frame_width * self._frame_height * 3 * 5
                )
            except FileNotFoundError:
                print("❌ ffmpeg tidak ditemukan.")
                return

            # Test koneksi dengan mencoba fetch segment pertama
            self.connected = True
            threading.Thread(target=self.hls_fetcher_loop, daemon=True).start()
            
            # Tunggu frame pertama
            for _ in range(20):
                if self.stop_event.is_set():
                    self._safe_release()
                    return
                time.sleep(0.5)
                frame = self._read_ffmpeg_frame()
                if frame is not None:
                    self.ret = True
                    self.frame = frame
                    print("✅ Koneksi HLS stream stabil.")
                    break
            
            if self.ret:
                break
            else:
                print(f"⚠️ Percobaan {i+1} gagal membaca frame dari HLS.")
                self.connected = False
                self._kill_ffmpeg()

        if self.ret:
            threading.Thread(target=self.update, daemon=True).start()
        else:
            print(f"❌ Gagal terhubung ke HLS stream.")
            self._safe_release()

    def hls_fetcher_loop(self):
        """Looping untuk mendownload segment HLS dan mem-pipe ke ffmpeg."""
        import requests
        import re
        
        base_url = self.src.split('?')[0].rsplit('/', 1)[0]
        params = self.src.split('?')[1] if '?' in self.src else ""
        key = ""
        if "key=" in params:
            key = params.split('key=')[1].split('&')[0]

        last_segment = None
        
        while self.connected and not self.stop_event.is_set():
            try:
                # 1. Download Playlist
                res = requests.get(self.src, timeout=5)
                if res.status_code != 200:
                    time.sleep(2)
                    continue
                
                # 2. Cari segment terbaru
                segments = re.findall(r'index\d+\.ts', res.text)
                if not segments:
                    time.sleep(1)
                    continue
                
                # Kita ambil segment terakhir
                newest_segment = segments[-1]
                
                if newest_segment != last_segment:
                    # 3. Download Segment dengan Key
                    seg_url = f"{base_url}/{newest_segment}?key={key}"
                    seg_res = requests.get(seg_url, timeout=5)
                    
                    if seg_res.status_code == 200:
                        # 4. Pipe ke ffmpeg stdin
                        if self._ffmpeg_proc and self._ffmpeg_proc.stdin:
                            try:
                                self._ffmpeg_proc.stdin.write(seg_res.content)
                                self._ffmpeg_proc.stdin.flush()
                            except BrokenPipeError:
                                break
                    
                    last_segment = newest_segment
                
                time.sleep(1) # HLS Purwakarta punya segment 2 detik
                
            except Exception as e:
                if DEBUG_MODE: print(f"⚠️ HLS Fetcher Error: {e}")
                time.sleep(2)

    def _init_rtsp(self):
        """Inisialisasi RTSP stream via cv2.VideoCapture."""
        max_retries = 5
        for i in range(max_retries):
            # Cek apakah engine sudah diminta berhenti sebelum retry
            if self.stop_event.is_set():
                self._safe_release()
                return

            print(f"📡 Mencoba menghubungkan ke kamera ({i+1}/{max_retries})...")
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            
            self.cap = cv2.VideoCapture(self.src, cv2.CAP_FFMPEG)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 15000)
            self.cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)

            # Interruptible sleep: cek stop_event setiap 0.5 detik
            for _ in range(4):
                if self.stop_event.is_set():
                    self._safe_release()
                    return
                time.sleep(0.5)
            
            # Cek lagi sebelum blocking read
            if self.stop_event.is_set():
                self._safe_release()
                return

            self.ret, self.frame = self.cap.read()
            if self.ret:
                print("✅ Koneksi kamera stabil.")
                break
            else:
                print(f"⚠️ Percobaan {i+1} gagal membaca frame.")
                # Interruptible sleep antara retry
                for _ in range(2):
                    if self.stop_event.is_set():
                        self._safe_release()
                        return
                    time.sleep(0.5)

        # Hanya start update thread jika koneksi berhasil dan belum di-stop
        if not self.stop_event.is_set() and self.ret:
            self.connected = True
            threading.Thread(target=self.update, daemon=True).start()
        elif not self.stop_event.is_set():
            # Semua retry gagal tapi bukan karena di-stop
            print(f"❌ Gagal terhubung ke kamera setelah {max_retries} percobaan.")
            self._safe_release()

    def _read_ffmpeg_frame(self):
        """Baca satu frame dari ffmpeg stdout pipe."""
        if self._ffmpeg_proc is None or self._ffmpeg_proc.poll() is not None:
            return None
        frame_size = self._frame_width * self._frame_height * 3
        try:
            raw = self._ffmpeg_proc.stdout.read(frame_size)
            if len(raw) != frame_size:
                return None
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(
                (self._frame_height, self._frame_width, 3)
            )
            return frame
        except Exception:
            return None

    def _kill_ffmpeg(self):
        """Terminate ffmpeg subprocess."""
        if self._ffmpeg_proc is not None:
            try:
                self._ffmpeg_proc.kill()
                self._ffmpeg_proc.wait(timeout=3)
            except Exception:
                pass
            self._ffmpeg_proc = None

    def _safe_release(self):
        """Release capture/ffmpeg dari thread yang sama yang memilikinya."""
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self._kill_ffmpeg()

    def update(self):
        while not self.stop_event.is_set():
            if self._is_hls:
                # HLS: baca dari ffmpeg pipe
                frame = self._read_ffmpeg_frame()
                if frame is not None:
                    self.ret = True
                    self.frame = frame
                else:
                    # FFmpeg mungkin crash/disconnect, coba restart
                    if self._ffmpeg_proc and self._ffmpeg_proc.poll() is not None:
                        print(f"⚠️ FFmpeg process terminated, mencoba reconnect HLS...")
                        self._kill_ffmpeg()
                        ffmpeg_cmd = [
                            'ffmpeg',
                            '-reconnect', '1',
                            '-reconnect_streamed', '1',
                            '-reconnect_delay_max', '5',
                            '-i', self.src,
                            '-f', 'rawvideo',
                            '-pix_fmt', 'bgr24',
                            '-vsync', '0',
                            '-an', '-sn',
                            '-v', 'error',
                            'pipe:1'
                        ]
                        try:
                            self._ffmpeg_proc = subprocess.Popen(
                                ffmpeg_cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                bufsize=self._frame_width * self._frame_height * 3 * 2
                            )
                        except Exception:
                            break
                    time.sleep(0.01)
            else:
                # RTSP: baca dari cv2.VideoCapture
                if self.cap is None:
                    break
                try:
                    ret, frame = self.cap.read()
                except Exception:
                    break
                if ret:
                    self.ret = ret
                    self.frame = frame
                else:
                    time.sleep(0.01)

            # Encode ke JPEG untuk dashboard monitoring (kedua mode)
            if self.ret and self.frame is not None:
                from frame_shared import latest_frames, frame_timestamps
                try:
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 65]
                    _, buffer = cv2.imencode('.jpg', self.frame, encode_param)
                    gid_int = int(self.gate_id)
                    latest_frames[gid_int] = buffer.tobytes()
                    frame_timestamps[gid_int] = time.time()
                except Exception:
                    pass

        # Release di thread yang sama (update thread) agar thread-safe
        self._safe_release()

    def read(self):
        return self.ret, self.frame

    def stop(self):
        """Signal stop — TIDAK release cap di sini untuk menghindari race condition.
        Release dilakukan oleh update thread atau constructor yang memiliki cap."""
        self.stop_event.set()

import frame_shared
from app import app

# =============================
# DASHBOARD API INTEGRATION
# =============================

DASHBOARD_API_URL = os.getenv("DASHBOARD_API_URL", "http://localhost:5173/api/v1/event")
DASHBOARD_CONFIG_URL = os.getenv("DASHBOARD_CONFIG_URL", "http://localhost:5173/api/v1/config")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "mata-plat-secret-api-key-2026").strip()
HMAC_SECRET = os.getenv("HMAC_SECRET", "").strip()
ENABLE_WINDOW = os.getenv("ENABLE_WINDOW", "False") == "True"
STREAM_PORT = int(os.getenv("STREAM_PORT", 5000))

def generate_hmac_signature(payload_str, timestamp, secret):
    message = f"{payload_str}.{timestamp}".encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()
    return signature

def get_hardware_id():
    hwid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".hwid")
    if os.path.exists(hwid_file):
        try:
            with open(hwid_file, "r") as f:
                return f.read().strip()
        except: pass

    try:
        import uuid
        new_id = uuid.uuid4().hex[:12]
        mac_hex = ':'.join(new_id[i:i+2] for i in range(0, 12, 2))
        with open(hwid_file, "w") as f:
            f.write(mac_hex)
        return mac_hex
    except:
        return "UNKNOWN"

def fetch_configs():
    """Fetch configuration from Dashboard API. Returns full response dict or None."""
    hwid = get_hardware_id()
    params = {"hwid": hwid}
    
    # Sign query parameters for GET
    import urllib.parse
    payload_str = urllib.parse.urlencode(params)
    timestamp = int(time.time())
    
    headers = {
        "x-api-key": DASHBOARD_API_KEY,
        "Content-Type": "application/json"
    }

    if HMAC_SECRET:
        signature = generate_hmac_signature(payload_str, timestamp, HMAC_SECRET)
        headers["x-signature"] = signature
        headers["x-timestamp"] = str(timestamp)

    try:
        response = requests.get(DASHBOARD_CONFIG_URL, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                return data  # Return full response (cameras + engineConfig)
            else:
                print(f"⚠️ Dashboard API mengembalikan success: false: {data.get('message', 'No message')}")
        elif response.status_code == 202:
            # Pending pairing — admin belum memasangkan HWID ini ke gate
            print(f"⏳ HWID {hwid} terdeteksi oleh Dashboard, menunggu dipasangkan oleh admin...")
        elif response.status_code == 401 or response.status_code == 403:
            print(f"❌ Dashboard API Authentication Error {response.status_code}: {response.text[:100]}")
        elif response.status_code == 404:
            # HWID belum dikenali atau endpoint belum di-deploy ulang
            print(f"⚠️ Dashboard mengembalikan 404. Perangkat belum terdaftar atau dashboard perlu rebuild.")
        else:
            print(f"❌ Dashboard API error {response.status_code}: {response.text[:100]}")
    except requests.exceptions.ConnectionError:
        print(f"❌ Gagal terhubung ke Dashboard (Connection Refused). Periksa URL: {DASHBOARD_CONFIG_URL}")
    except requests.exceptions.Timeout:
        print(f"❌ Timeout saat menghubungi Dashboard ({DASHBOARD_CONFIG_URL})")
    except Exception as e:
        print(f"❌ Error saat mengambil konfigurasi: {str(e)}")
    
    return None

def apply_engine_config(engine_config):
    """Apply engine configuration received from Dashboard to global variables."""
    global FRAME_SKIP, STOP_DISTANCE, MOVE_DISTANCE
    global STOP_CONFIRM_FRAMES, MOVE_CONFIRM_FRAMES
    global VEHICLE_CLASSES, PLATE_REGEX

    if not engine_config:
        return

    changed = []

    new_val = engine_config.get('frameSkip')
    if new_val is not None and new_val != FRAME_SKIP:
        changed.append(f"FRAME_SKIP: {FRAME_SKIP} → {new_val}")
        FRAME_SKIP = int(new_val)

    new_val = engine_config.get('stopDistance')
    if new_val is not None and new_val != STOP_DISTANCE:
        changed.append(f"STOP_DISTANCE: {STOP_DISTANCE} → {new_val}")
        STOP_DISTANCE = int(new_val)

    new_val = engine_config.get('moveDistance')
    if new_val is not None and new_val != MOVE_DISTANCE:
        changed.append(f"MOVE_DISTANCE: {MOVE_DISTANCE} → {new_val}")
        MOVE_DISTANCE = int(new_val)

    new_val = engine_config.get('stopConfirmFrames')
    if new_val is not None and new_val != STOP_CONFIRM_FRAMES:
        changed.append(f"STOP_CONFIRM_FRAMES: {STOP_CONFIRM_FRAMES} → {new_val}")
        STOP_CONFIRM_FRAMES = int(new_val)

    new_val = engine_config.get('moveConfirmFrames')
    if new_val is not None and new_val != MOVE_CONFIRM_FRAMES:
        changed.append(f"MOVE_CONFIRM_FRAMES: {MOVE_CONFIRM_FRAMES} → {new_val}")
        MOVE_CONFIRM_FRAMES = int(new_val)

    new_val = engine_config.get('vehicleClasses')
    if new_val is not None and new_val != VEHICLE_CLASSES:
        changed.append(f"VEHICLE_CLASSES: {VEHICLE_CLASSES} → {new_val}")
        VEHICLE_CLASSES = list(new_val)

    new_val = engine_config.get('plateRegex')
    if new_val is not None and new_val != PLATE_REGEX:
        changed.append(f"PLATE_REGEX: {PLATE_REGEX} → {new_val}")
        PLATE_REGEX = str(new_val)

    if changed:
        print(f"🔄 Konfigurasi Engine diperbarui dari Dashboard:")
        for c in changed:
            print(f"   ↳ {c}")

def sync_to_dashboard(plate, action, gate_id, v_type_id=1):
    try:
        data = {
            "plate": plate,
            "action": action.lower(),
            "gate_id": gate_id,
            "vehicle_type_id": v_type_id
        }
        
        # Use separators to ensure consistent JSON formatting for HMAC
        payload_str = json.dumps(data, separators=(',', ':'))
        timestamp = int(time.time())
        
        headers = {
            "x-api-key": DASHBOARD_API_KEY,
            "Content-Type": "application/json"
        }

        if HMAC_SECRET:
            signature = generate_hmac_signature(payload_str, timestamp, HMAC_SECRET)
            headers["x-signature"] = signature
            headers["x-timestamp"] = str(timestamp)
            
        response = requests.post(DASHBOARD_API_URL, data=payload_str, headers=headers, timeout=10)
        if response.status_code in [200, 201]:
            print(f"📡 Sync {action}: [{plate}] @ Camera {gate_id} (Status: {response.status_code})")
        else:
            print(f"❌ Dashboard menolak data ({response.status_code}): {response.text[:100]}")
    except requests.exceptions.Timeout:
        print(f"❌ Timeout saat mengirim data {action} ke Dashboard")
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Failed to sync {action}: {str(e)}")

# =============================
# OCR SYSTEM
# =============================

ocr_queue = Queue()

def preprocess_plate(img):
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    gray = clahe.apply(gray)
    return gray

def validate_plate(text):
    text = re.sub(r'[^A-Z0-9]', '', text.upper())
    if len(text) < 4: return None
    to_alpha = str.maketrans('01245678', 'OIZASGTB') 
    to_num   = str.maketrans('OIZASGTB', '01245678')
    match = re.search(r'^([A-Z0-9]{1,2})([0-9A-Z]{1,4})([A-Z0-9]{1,3})$', text)
    if not match: return None
    pref, mid, suff = match.groups()
    pref = pref.translate(to_alpha); mid = mid.translate(to_num); suff = suff.translate(to_alpha)
    final = pref + mid + suff
    if re.match(PLATE_REGEX, final): return final
    return None

def ocr_worker():
    while True:
        tid, crop, target_dict = ocr_queue.get()
        try:
            img = preprocess_plate(crop)
            result = ocr.ocr(img, cls=False)
            plate = ""
            if result and result[0]:
                for line in result[0]:
                    plate += str(line[1][0])
            plate = validate_plate(plate)
            if plate and tid in target_dict:
                target_dict[tid]["plat"] = plate
                if DEBUG_MODE:
                    print(f"✅ [OCR] Berhasil mendeteksi plat: {plate} untuk ID:{tid}")
        except: pass
        ocr_queue.task_done()

threading.Thread(target=ocr_worker, daemon=True).start()

# =============================
# ENGINE INSTANCE
# =============================

class CamEngine:
    def __init__(self, config):
        self.config = config
        self.gate_id = config['id']
        self.name = config['name']
        self.url = config['cameraUrl']
        self.type = str(config.get('deviceType', config.get('type', ''))).strip()
        print(f"DEBUG: [Cam:{self.name}] Detected Type: '{self.type}'")
        self.parking_data = {}
        self.running = True
        self._stop_event = threading.Event()  # Shared stop signal
        self.cap = None
        self.last_cleanup_time = time.time()
        
        # Menggunakan Global Shared Models agar hemat VRAM
        self.model_vehicle = model_vehicle
        self.model_plate = model_plate

    def stop(self):
        print(f"🛑 Menghentikan Engine: {self.name}")
        self.running = False
        self._stop_event.set()  # Signal semua komponen untuk berhenti
        if self.cap:
            self.cap.stop()  # Hanya set stop_event, tidak release langsung
        if ENABLE_WINDOW:
            try: cv2.destroyWindow(f"CAM: {self.name}")
            except: pass

    def cleanup_old_data(self):
        current_time = time.time()
        if current_time - self.last_cleanup_time < CLEANUP_INTERVAL:
            return
            
        tids_to_remove = []
        for tid, data in self.parking_data.items():
            if current_time - data.get("last_seen", 0) > IDLE_TIMEOUT:
                tids_to_remove.append(tid)
        
        for tid in tids_to_remove:
            del self.parking_data[tid]
            
        if tids_to_remove and DEBUG_MODE:
            print(f"🧹 [CamEngine:{self.name}] Membersihkan {len(tids_to_remove)} Tracker ID lama.")
            
        self.last_cleanup_time = current_time

    def process(self):
        print(f"🚀 Memulai Engine: {self.name} ({self.type})")
        self.cap = VideoCaptureAsync(self.url, self.gate_id, stop_event=self._stop_event)
        
        # Jika koneksi dibatalkan atau gagal total
        if not self.cap.connected:
            if self._stop_event.is_set():
                print(f"⚠️ Engine {self.name} dibatalkan saat menghubungkan kamera.")
            else:
                print(f"❌ Engine {self.name} gagal terhubung ke kamera.")
            return
        
        # Load AI Throttle dari .env
        ai_speed = float(os.getenv("AI_THROTTLE", "0.3"))
        last_ai_time = 0
        
        print(f"⚙️ AI Throttle: {ai_speed}s ({1/ai_speed:.1f} FPS)")

        while self.running:
            try:
                ret, frame = self.cap.read()
            except Exception:
                break
            if not ret or frame is None:
                time.sleep(0.01)
                continue
            
            # Throttle AI secara dinamis berdasarkan konfigurasi .env
            current_time = time.time()
            if current_time - last_ai_time < ai_speed:
                time.sleep(0.005) # Jeda sangat kecil untuk efisiensi CPU
                continue
                
            last_ai_time = current_time
            
            # Panggil pembersihan data secara berkala
            self.cleanup_old_data()
            
            # Gunakan model lokal agar tracker tidak bercampur antar kamera
            results = self.model_vehicle.track(frame, persist=True, conf=0.35, imgsz=640, verbose=False)
            current_ids = set()

            if results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
                ids = results[0].boxes.id.cpu().numpy().astype(int)
                clss = results[0].boxes.cls.cpu().numpy().astype(int)

                for box, tid, cls_idx in zip(boxes, ids, clss):
                    if cls_idx not in VEHICLE_CLASSES: continue
                    current_ids.add(tid)

                    if tid not in self.parking_data:
                        self.parking_data[tid] = {
                            "plat": "Scanning...", "positions": [], "state": "moving",
                            "stop_counter": 0, "move_counter": 0, "park_start": None,
                            "ocr_time": 0, "db_saved": False, "last_seen": time.time()
                        }
                        if DEBUG_MODE:
                            print(f"🆕 [Cam:{self.name}] Terdeteksi kendaraan baru (ID:{tid})")

                    p = self.parking_data[tid]
                    x1, y1, x2, y2 = box
                    center = (int((x1+x2)/2), int((y1+y2)/2))
                    p["positions"].append(center)
                    p["last_seen"] = time.time()
                    if len(p["positions"]) > 5: p["positions"].pop(0)

                    dist = 0
                    if len(p["positions"]) >= 2:
                        dist = np.linalg.norm(np.array(p["positions"][-1]) - np.array(p["positions"][0]))

                    if dist < STOP_DISTANCE:
                        p["stop_counter"] += 1; p["move_counter"] = 0
                    elif dist > MOVE_DISTANCE:
                        p["move_counter"] += 1; p["stop_counter"] = 0

                    if p["stop_counter"] >= STOP_CONFIRM_FRAMES and p["state"] != "stopped":
                        p["state"] = "stopped"; p["park_start"] = time.time()
                        if DEBUG_MODE:
                            print(f"🛑 [Cam:{self.name}] Kendaraan ID:{tid} BERHENTI. Memulai pemindaian plat...")
                    if p["move_counter"] >= MOVE_CONFIRM_FRAMES and p["state"] != "moving":
                        p["state"] = "moving"; p["park_start"] = None
                        if DEBUG_MODE:
                            print(f"🚗 [Cam:{self.name}] Kendaraan ID:{tid} BERGERAK kembali.")

                    is_parking = (p["state"] == "stopped")

                    if is_parking and time.time() - p["ocr_time"] > 2:
                        roi = frame[y1:y2, x1:x2]
                        plate_res = self.model_plate.predict(roi, conf=0.35, imgsz=320, verbose=False)
                        if len(plate_res[0].boxes) > 0:
                            pb = plate_res[0].boxes.xyxy[0].cpu().numpy().astype(int)
                            crop = roi[pb[1]:pb[3], pb[0]:pb[2]]
                            if crop.size > 0:
                                ocr_queue.put((tid, crop, self.parking_data))
                                p["ocr_time"] = time.time()

                    # KIRIM DATA: Biarkan data masuk dulu meskipun plat belum terbaca
                    if is_parking and not p["db_saved"]:
                        # Jika plat belum ketemu, gunakan placeholder UNKNOWN dengan ID tracker
                        display_plate = p["plat"] if p["plat"] != "Scanning..." else f"TANPA-PLAT-{tid}"
                        
                        # Tentukan action, semua monitoring dianggap entry
                        cam_type_lower = self.type.lower()
                        is_monitoring = "monitoring" in cam_type_lower or "entry" in cam_type_lower
                        action = 'entry' if is_monitoring else 'exit'
                        
                        sync_to_dashboard(display_plate, action, self.gate_id)
                        
                        # Jika sudah ada plat asli, tandai sudah tersimpan permanen
                        # Jika masih placeholder, biarkan db_saved=False agar bisa diupdate nanti saat plat ketemu
                        if p["plat"] != "Scanning...":
                            p["db_saved"] = True
                            p["placeholder_sent"] = False
                        else:
                            p["placeholder_sent"] = True
                            p["db_saved"] = True # Set True sementara agar tidak spam tiap frame

                    # UPDATE DATA: Jika sebelumnya kirim placeholder, dan sekarang plat asli sudah ketemu
                    if p.get("placeholder_sent") and p["plat"] != "Scanning...":
                        cam_type_lower = self.type.lower()
                        is_monitoring = "monitoring" in cam_type_lower or "entry" in cam_type_lower
                        action = 'entry' if is_monitoring else 'exit'
                        
                        print(f"🔄 [Cam:{self.name}] Mengupdate data placeholder ID:{tid} dengan plat asli: {p['plat']}")
                        sync_to_dashboard(p["plat"], action, self.gate_id)
                        p["placeholder_sent"] = False
                        p["db_saved"] = True

                    color = (0, 255, 0) if is_parking else (0, 165, 255)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, f"{p['plat']} ({self.name})", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

            # Monitoring stream is now handled by VideoCaptureAsync thread for better performance
            if ENABLE_WINDOW:
                cv2.imshow(f"CAM: {self.name}", cv2.resize(frame, (640, 360)))
                if cv2.waitKey(1) == 27: break

def start_flask():
    from waitress import serve
    print(f"🌐 Starting Production Streaming Server on port {STREAM_PORT}...")
    serve(app, host="0.0.0.0", port=STREAM_PORT, _quiet=True)

import signal

def main():
    started_engines = {} # gate_id -> CamEngine
    running = True

    def graceful_shutdown(signum=None, frame=None):
        nonlocal running
        sig_name = signal.Signals(signum).name if signum else "UNKNOWN"
        print(f"\n🛑 Menerima sinyal {sig_name}, menghentikan semua engine...")
        running = False
        for gid, eng in started_engines.items():
            eng.stop()
        print("✅ Semua engine dihentikan. Bye!")
        sys.exit(0)  # Exit code 0 agar PM2 tahu ini bukan crash

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    threading.Thread(target=start_flask, daemon=True).start()
    
    print("🚀 Mata Plat Engine Manager Aktif (Polling setiap 30 detik)")
    
    while running:
        try:
            response_data = fetch_configs()
            if response_data is None:
                if not started_engines:
                    print("⏳ Menunggu konfigurasi awal dari Dashboard...")
                else:
                    print("⚠️ Gagal sinkronisasi konfigurasi, mencoba lagi...")
            else:
                # Apply engine configuration from Dashboard
                apply_engine_config(response_data.get('engineConfig'))

                configs = response_data.get('cameras', [])
                current_active_ids = [str(c['id']) for c in configs if c.get('isActive', True)]
                
                # 1. Hentikan engine yang tidak lagi aktif atau dihapus
                for gid in list(started_engines.keys()):
                    if gid not in current_active_ids:
                        started_engines[gid].stop()
                        del started_engines[gid]
                
                # 2. Jalankan engine baru atau update yang berubah
                for cfg in configs:
                    if not cfg.get('isActive', True): continue
                    
                    gid = str(cfg['id'])
                    if gid not in started_engines:
                        engine = CamEngine(cfg)
                        started_engines[gid] = engine
                        threading.Thread(target=engine.process, daemon=True).start()
                    else:
                        # Cek jika URL berubah (perlu restart thread)
                        if started_engines[gid].url != cfg['cameraUrl']:
                            print(f"🔄 Konfigurasi berubah untuk {cfg['name']}, merestart thread...")
                            started_engines[gid].stop()
                            engine = CamEngine(cfg)
                            started_engines[gid] = engine
                            threading.Thread(target=engine.process, daemon=True).start()
                            
        except Exception as e:
            if not running:
                break
            print(f"❌ Error in Manager Loop: {e}")
            
        # Sleep dalam interval kecil agar bisa di-interrupt dengan bersih
        for _ in range(30):
            if not running:
                break
            time.sleep(1)

if __name__ == "__main__":
    main()