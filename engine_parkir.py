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
import mysql.connector
from dotenv import load_dotenv
import torch

load_dotenv()

# Setup CLI Arguments
parser = argparse.ArgumentParser(description='Mata Plat Engine - AI Parking System')
args = parser.parse_args()

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
# DATABASE
# =============================

db = mysql.connector.connect(
    host=os.getenv("DB_HOST", "localhost"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASS", ""),
    database=os.getenv("DB_NAME", "parking_db")
)

cursor = db.cursor()

BIAYA_PER_JAM = int(os.getenv("BIAYA_PER_JAM", 5000))

# =============================
# KONFIGURASI
# =============================

FRAME_SKIP = 2
STOP_DISTANCE = 3
MOVE_DISTANCE = 8
STOP_CONFIRM_FRAMES = 10
MOVE_CONFIRM_FRAMES = 4
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

class VideoCaptureAsync:
    def __init__(self, src, gate_id):
        self.src = src
        self.gate_id = gate_id
        self.cap = None
        self.ret = False
        self.frame = None
        self.running = True

        max_retries = 5
        for i in range(max_retries):
            print(f"📡 Mencoba menghubungkan ke kamera ({i+1}/{max_retries})...")
            if self.cap is not None:
                self.cap.release()
            
            self.cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            time.sleep(2)
            
            self.ret, self.frame = self.cap.read()
            if self.ret:
                print("✅ Koneksi kamera stabil.")
                break
            else:
                print(f"⚠️ Percobaan {i+1} gagal membaca frame.")
                time.sleep(1)

        threading.Thread(target=self.update, daemon=True).start()

    def update(self):
        while self.running:
            if self.cap is None: break
            ret, frame = self.cap.read()
            if ret:
                self.ret = ret
                self.frame = frame
                # Update frame_shared secara real-time di sini (sebelum AI)
                # Ini memastikan stream dashboard selalu 30 FPS mengikuti kamera
                from frame_shared import latest_frames
                # Simpan frame original untuk stream cepat
                latest_frames[f"raw_{self.gate_id}"] = frame
            else:
                time.sleep(0.01)

    def read(self):
        return self.ret, self.frame

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()

import frame_shared
from app import app

# =============================
# DASHBOARD API INTEGRATION
# =============================

DASHBOARD_API_URL = os.getenv("DASHBOARD_API_URL", "http://localhost:5173/api/v1/event")
DASHBOARD_CONFIG_URL = os.getenv("DASHBOARD_CONFIG_URL", "http://localhost:5173/api/v1/config")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "mata-plat-secret-api-key-2026").strip()
ENABLE_WINDOW = os.getenv("ENABLE_WINDOW", "False") == "True"
STREAM_PORT = int(os.getenv("STREAM_PORT", 5000))

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
    headers = {"x-api-key": DASHBOARD_API_KEY}
    hwid = get_hardware_id()
    params = {"hwid": hwid}

    try:
        response = requests.get(DASHBOARD_CONFIG_URL, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                return data.get('cameras')
            else:
                print(f"⚠️ Dashboard API mengembalikan success: false: {data.get('message', 'No message')}")
        elif response.status_code == 202:
            # Pending pairing — admin belum memasangkan HWID ini ke gate
            print(f"⏳ HWID {hwid} terdeteksi oleh Dashboard, menunggu dipasangkan oleh admin...")
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

def sync_to_dashboard(plate, action, gate_id, v_type_id=1):
    try:
        headers = {"x-api-key": DASHBOARD_API_KEY}
        data = {
            "plate": plate,
            "action": action.lower(),
            "gate_id": gate_id,
            "vehicle_type_id": v_type_id
        }
        requests.post(DASHBOARD_API_URL, json=data, headers=headers, timeout=5)
        print(f"📡 Sync {action}: [{plate}] @ Camera {gate_id}")
    except: pass

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
        self.type = config['type']
        self.parking_data = {}
        self.running = True
        self.cap = None
        
        # Menggunakan Global Shared Models agar hemat VRAM
        self.model_vehicle = model_vehicle
        self.model_plate = model_plate

    def stop(self):
        print(f"🛑 Menghentikan Engine: {self.name}")
        self.running = False
        if self.cap:
            self.cap.stop()
        if ENABLE_WINDOW:
            try: cv2.destroyWindow(f"CAM: {self.name}")
            except: pass

    def process(self):
        print(f"🚀 Memulai Engine: {self.name} ({self.type})")
        self.cap = VideoCaptureAsync(self.url, self.gate_id)
        frame_count = 0

        while self.running:
            ret, frame = self.cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue
            
            # AI always takes the LATEST frame from the async buffer
            # no more rigid frame skipping to ensure real-time feel

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
                            "ocr_time": 0, "db_saved": False
                        }

                    p = self.parking_data[tid]
                    x1, y1, x2, y2 = box
                    center = (int((x1+x2)/2), int((y1+y2)/2))
                    p["positions"].append(center)
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
                    if p["move_counter"] >= MOVE_CONFIRM_FRAMES and p["state"] != "moving":
                        p["state"] = "moving"; p["park_start"] = None

                    is_parking = (p["state"] == "stopped")

                    if is_parking and time.time() - p["ocr_time"] > 2:
                        roi = frame[y1:y2, x1:x2]
                        plate_res = self.model_plate.predict(roi, conf=0.45, imgsz=320, verbose=False)
                        if len(plate_res[0].boxes) > 0:
                            pb = plate_res[0].boxes.xyxy[0].cpu().numpy().astype(int)
                            crop = roi[pb[1]:pb[3], pb[0]:pb[2]]
                            if crop.size > 0:
                                ocr_queue.put((tid, crop, self.parking_data))
                                p["ocr_time"] = time.time()

                    if is_parking and p["plat"] != "Scanning..." and not p["db_saved"]:
                        action = 'entry' if self.type == 'entry_gate' else 'exit' if self.type == 'exit_gate' else 'monitoring'
                        sync_to_dashboard(p["plat"], action, self.gate_id)
                        p["db_saved"] = True

                    color = (0, 255, 0) if is_parking else (0, 165, 255)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, f"{p['plat']} ({self.name})", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

            # 1. Update annotated frame (resized for dashboard)
            h, w = frame.shape[:2]
            preview_w = 800
            preview_h = int(h * (preview_w / w))
            preview_frame = cv2.resize(frame, (preview_w, preview_h))
            
            # 2. Pre-encode to JPEG (Do it ONCE here, instead of for every client in Flask)
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 70]
            ret, buffer = cv2.imencode('.jpg', preview_frame, encode_param)
            if ret:
                # Simpan dalam bentuk bytes agar Flask tinggal kirim (sangat cepat)
                frame_shared.latest_frames[self.gate_id] = buffer.tobytes()
            
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
            configs = fetch_configs()
            if configs is None:
                if not started_engines:
                    print("⏳ Menunggu konfigurasi awal dari Dashboard...")
                else:
                    print("⚠️ Gagal sinkronisasi konfigurasi, mencoba lagi...")
            else:
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