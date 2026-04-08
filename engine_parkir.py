import os
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
parser.add_argument('--gate', type=str, help='ID Gerbang (misal: 1 atau 3)')
args = parser.parse_args()

# DETEKSI DEVICE (GPU/CPU)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DEBUG_MODE = os.getenv("DEBUG_MODE", "False") == "True"
print(f"🚀 Menggunakan Device: {DEVICE}")
print(f"🔧 Debug Mode: {'AKTIF' if DEBUG_MODE else 'NON-AKTIF'}")

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

RTSP_URL = os.getenv("RTSP_URL", "rtsp://admin:m3diapratama@10.232.88.154:554/stream")

FRAME_SKIP = 2

# Movement thresholds
STOP_DISTANCE = 3
MOVE_DISTANCE = 8

STOP_CONFIRM_FRAMES = 10
MOVE_CONFIRM_FRAMES = 4

VEHICLE_CLASSES = [2,3,5,7]

PLATE_REGEX = r'^[A-Z]{1,2}[0-9]{1,4}[A-Z]{1,3}$'

# =============================
# MODEL
# =============================

model_vehicle = YOLO("yolov8l.pt")
model_vehicle.to(DEVICE)

model_plate = YOLO("license_plate_detector.pt")
model_plate.to(DEVICE)

ocr = PaddleOCR(lang="en")

# =============================
# ASYNC CAMERA
# =============================

class VideoCaptureAsync:

    def __init__(self, src):
        self.src = src
        self.cap = None
        self.ret = False
        self.frame = None
        self.running = True

        # Retry logic untuk inisialisasi awal
        max_retries = 5
        for i in range(max_retries):
            print(f"📡 Mencoba menghubungkan ke kamera ({i+1}/{max_retries})...")
            if self.cap is not None:
                self.cap.release()
                
            self.cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # Beri waktu FFmpeg untuk handshake
            time.sleep(2)
            
            self.ret, self.frame = self.cap.read()
            if self.ret:
                print("✅ Koneksi kamera stabil.")
                break
            else:
                print(f"⚠️ Percobaan {i+1} gagal membaca frame.")
                time.sleep(1)

        if not self.ret:
             print(f"❌ VideoCaptureAsync: Gagal total membaca dari {src}")

        threading.Thread(target=self.update, daemon=True).start()

    def update(self):

        while self.running:
            # Selalu ambil frame paling baru dari stream
            ret,frame=self.cap.read()

            if ret:
                self.ret=ret
                self.frame=frame
            
            # Jika buffer mulai menumpuk, lewati frame lama (opsional untuk stream RTSP)
            # time.sleep(0.001)

    def read(self):

        return self.ret,self.frame

import frame_shared
from app import app
import requests

# =============================
# DASHBOARD API INTEGRATION
# =============================

# Setup CLI Arguments
parser = argparse.ArgumentParser(description='Mata Plat Engine - AI Parking System')
parser.add_argument('--gate', type=str, help='ID Gerbang (default dari .env)')
args = parser.parse_args()

DASHBOARD_API_URL = os.getenv("DASHBOARD_API_URL", "http://localhost:5173/api/v1/event")
DASHBOARD_CONFIG_URL = os.getenv("DASHBOARD_CONFIG_URL", "http://localhost:5173/api/v1/config")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "mata-plat-secret-api-key-2026")
ENABLE_WINDOW = os.getenv("ENABLE_WINDOW", "False") == "True"
STREAM_PORT = int(os.getenv("STREAM_PORT", 5000))
GATE_ID = args.gate if args.gate else os.getenv("GATE_ID", "1")

def get_hardware_id():
    """Mengambil MAC Address sebagai identitas unik (Hardware ID)"""
    try:
        import uuid
        mac_num = uuid.getnode()
        mac_hex = ':'.join(['{:02x}'.format((mac_num >> i) & 0xff) for i in range(0, 8*6, 8)][::-1])
        return mac_hex
    except Exception as e:
        print(f"⚠️ Gagal mendapatkan Hardware ID: {e}")
        return "UNKNOWN"

def fetch_camera_config():
    """Mengambil URL Kamera dari Dashboard API berdasarkan HWID atau GATE_ID"""
    headers = {"x-api-key": DASHBOARD_API_KEY}
    hwid = get_hardware_id()
    
    print(f"📡 Mencari konfigurasi...")
    print(f"🆔 Hardware ID: {hwid}")
    
    # Prioritaskan HWID, gunakan GATE_ID sebagai fallback jika diberikan lewat CLI
    params = {"hwid": hwid}
    if args.gate:
        params = {"id": args.gate}
        print(f"📍 Menggunakan Override Gate ID: {args.gate}")

    max_retries = 3
    for i in range(max_retries):
        try:
            response = requests.get(DASHBOARD_CONFIG_URL, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                config = response.json()
                if config.get('success'):
                    print(f"✅ Gerbang ditemukan: {config.get('name')}")
                    print(f"📸 URL Kamera: {config.get('cameraUrl')}")
                    
                    # Update global GATE_ID agar log event selanjutnya akurat
                    global GATE_ID
                    GATE_ID = config.get('id')
                    
                    return config.get('cameraUrl')
            elif response.status_code == 404:
                error_data = response.json()
                if error_data.get('unrecognized'):
                    print(f"❌ PERANGKAT BELUM TERDAFTAR!")
                    print(f"👉 Harap pasangkan Hardware ID ini di Dashboard: {hwid}")
                return None
        except Exception as e:
            print(f"⚠️ Gagal menghubungi dashboard (Percobaan {i+1}/{max_retries}): {e}")
            time.sleep(2)
    return None

def sync_to_dashboard(plate, action, v_type_id=1):
    try:
        headers = {"x-api-key": DASHBOARD_API_KEY}
        data = {
            "plate": plate,
            "action": action.lower(),
            "gate_id": GATE_ID,
            "vehicle_type_id": v_type_id
        }
        res = requests.post(DASHBOARD_API_URL, json=data, headers=headers, timeout=5)
        print(f"📡 Sync {action}: {plate} -> Dashboard (Status: {res.status_code})")
    except Exception as e:
        print(f"❌ Dashboard Sync Error: {e}")

def vehicle_enter(plate):
    # Local Save (Legacy)
    cursor.execute(
        "INSERT INTO logs (plate,time_in) VALUES (%s,NOW())",
        (plate,)
    )
    db.commit()
    # Sync to Dashboard
    sync_to_dashboard(plate, 'entry')

def vehicle_exit(plate):
    cursor.execute(
        "SELECT id,time_in FROM logs WHERE plate=%s AND time_out IS NULL",
        (plate,)
    )
    data = cursor.fetchone()
    if data:
        log_id,time_in=data
        duration=(time.time()-time_in.timestamp())/3600
        total=int(duration*BIAYA_PER_JAM)
        cursor.execute(
            "UPDATE logs SET time_out=NOW(),total_bill=%s WHERE id=%s",
            (total,log_id)
        )
        db.commit()
    # Sync to Dashboard
    sync_to_dashboard(plate, 'exit')

# =============================
# ... (rest of the file until main loop) ...
# OCR SYSTEM
# =============================

ocr_queue=Queue()
parking_data={}

def preprocess_plate(img):
    # Perbesar gambar untuk detail lebih baik
    img=cv2.resize(img,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)

    # Convert ke Gray
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)

    # Noise reduction ringan agar tidak merusak karakter
    gray=cv2.bilateralFilter(gray,9,75,75)

    # Kita tidak lagi menggunakan adaptiveThreshold secara agresif
    # karena PaddleOCR bekerja lebih baik pada kontras alami.
    # Namun, kita tingkatkan kontras menggunakan CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    gray = clahe.apply(gray)

    return gray

def validate_plate(text):
    # 1. Pembersihan awal (Hapus spasi dan simbol)
    text = re.sub(r'[^A-Z0-9]', '', text.upper())
    if len(text) < 4: return None

    # 2. Logika Koreksi Berdasarkan Posisi (Standard Plat Indonesia)
    # Format: [HURUF (1-2)] [ANGKA (1-4)] [HURUF (1-3)]
    
    # Mapping karakter yang sering tertukar
    to_alpha = str.maketrans('01245678', 'OIZASGTB') 
    to_num   = str.maketrans('OIZASGTB', '01245678')
    
    # Mencoba mencari pembagian blok paling masuk akal
    # Kita cari angka pertama dan angka terakhir di tengah
    match = re.search(r'^([A-Z0-9]{1,2})(\d{1,4})([A-Z0-9]{1,3})$', text)
    
    if match:
        pref, mid, suff = match.groups()
    else:
        # Jika tidak ada blok angka yang jelas, coba tebak pembagian 2-4-2
        # atau gunakan regex fleksibel
        match = re.search(r'^([A-Z0-9]{1,2})([A-Z0-9]{1,4})([A-Z0-9]{1,3})$', text)
        if not match: return None
        pref, mid, suff = match.groups()

    # Koreksi Karakter
    pref = pref.translate(to_alpha).replace(" ", "")
    mid  = mid.translate(to_num).replace(" ", "")
    suff = suff.translate(to_alpha).replace(" ", "")

    # Gabungkan kembali
    final = pref + mid + suff

    # Validasi akhir dengan regex utama
    if re.match(PLATE_REGEX, final):
        return final

    return None

# =============================
# OCR WORKER
# =============================

def ocr_worker():

    while True:

        tid,crop=ocr_queue.get()

        try:
            img=preprocess_plate(crop)
            
            # Pada versi stable 2.x, ocr() mengembalikan list of pages
            # Setiap page berisi list of [box, (text, confidence)]
            result=ocr.ocr(img, cls=False)

            plate=""

            if result and isinstance(result, list):
                for line in result:
                    if line is None: continue
                    for res in line:
                        # res format: [[x,y], [x,y], [x,y], [x,y]], ('TEXT', 0.99)
                        if isinstance(res, list) and len(res) > 1:
                            text_info = res[1]
                            if isinstance(text_info, tuple) and len(text_info) > 0:
                                plate += str(text_info[0])

            plate=validate_plate(plate)

            if plate and tid in parking_data:
                parking_data[tid]["plat"]=plate

        except Exception as e:
            print("OCR ERROR:",e)

        ocr_queue.task_done()

threading.Thread(target=ocr_worker,daemon=True).start()

# =============================
# MAIN ENGINE
# =============================

def main():
    # Fetch camera config from Dashboard
    camera_url = None
    retry_count = 0
    max_retries = 5

    while camera_url is None and retry_count < max_retries:
        camera_url = fetch_camera_config()
        if camera_url is None:
            retry_count += 1
            print(f"🔄 Mengulang pengambilan config dalam 5 detik ({retry_count}/{max_retries})...")
            time.sleep(5)

    if camera_url is None:
        print("❌ Gagal mendapatkan konfigurasi kamera setelah beberapa percobaan. Engine dihentikan.")
        os._exit(1)

    cap = VideoCaptureAsync(camera_url)
    frame_count = 0
    fail_count = 0

    while True:
        ret, frame = cap.read()

        if not ret:
            fail_count += 1
            if fail_count > 50:
                print("❌ Koneksi kamera terputus secara permanen. Menghentikan program...")
                # Berikan waktu sebentar untuk print pesan
                time.sleep(1)
                os._exit(1) # Gunakan os._exit untuk mematikan semua thread sekaligus
            continue
        
        fail_count = 0 # Reset jika berhasil ambil frame

        frame_count+=1

        if frame_count % FRAME_SKIP !=0:
            continue

        results=model_vehicle.track(
            frame,
            persist=True,
            conf=0.35,
            imgsz=960,
            tracker="bytetrack.yaml",
            device=DEVICE,
            verbose=False
        )

        current_ids=set()

        if results[0].boxes.id is not None:

            boxes=results[0].boxes.xyxy.cpu().numpy().astype(int)
            ids=results[0].boxes.id.cpu().numpy().astype(int)
            clss=results[0].boxes.cls.cpu().numpy().astype(int)

            for box,tid,cls_idx in zip(boxes,ids,clss):

                # Di Debug Mode, kita proses semua kelas. Normalnya hanya VEHICLE_CLASSES.
                if not DEBUG_MODE and cls_idx not in VEHICLE_CLASSES:
                    continue

                current_ids.add(tid)

                x1,y1,x2,y2=box
                center=(int((x1+x2)/2),int((y1+y2)/2))

                if tid not in parking_data:

                    parking_data[tid]={
                        "plat":"Scanning...",
                        "positions":[],
                        "state":"moving",
                        "stop_counter":0,
                        "move_counter":0,
                        "park_start":None,
                        "ocr_time":0,
                        "db_saved":False
                    }

                p=parking_data[tid]

                # =============================
                # POSITION HISTORY
                # =============================

                p["positions"].append(center)

                if len(p["positions"])>5:
                    p["positions"].pop(0)

                dist=0

                if len(p["positions"])>=2:

                    dist=np.linalg.norm(
                        np.array(p["positions"][-1]) -
                        np.array(p["positions"][0])
                    )

                # =============================
                # STATE MACHINE
                # =============================

                if dist < STOP_DISTANCE:

                    p["stop_counter"]+=1
                    p["move_counter"]=0

                elif dist > MOVE_DISTANCE:

                    p["move_counter"]+=1
                    p["stop_counter"]=0

                # STOP CONFIRM
                if p["stop_counter"]>=STOP_CONFIRM_FRAMES:

                    if p["state"]!="stopped":

                        p["state"]="stopped"
                        p["park_start"]=time.time()

                # MOVE CONFIRM
                if p["move_counter"]>=MOVE_CONFIRM_FRAMES:

                    if p["state"]!="moving":

                        p["state"]="moving"
                        p["park_start"]=None

                # Di Debug Mode, abaikan status parkir (langsung dianggap parkir)
                is_parking = True if DEBUG_MODE else (p["state"]=="stopped")

                # =============================
                # OCR
                # =============================

                if is_parking and time.time()-p["ocr_time"]>2:

                    roi=frame[y1:y2,x1:x2]

                    plate_res=model_plate.predict(
                        roi,
                        conf=0.45,
                        imgsz=416,
                        device=DEVICE,
                        verbose=False
                    )

                    if len(plate_res[0].boxes)>0:

                        pb=plate_res[0].boxes.xyxy[0].cpu().numpy().astype(int)

                        crop=roi[pb[1]:pb[3],pb[0]:pb[2]]

                        if crop.size>0:

                            ocr_queue.put((tid,crop))
                            p["ocr_time"]=time.time()

                # =============================
                # DATABASE SAVE
                # =============================

                if is_parking and p["plat"]!="Scanning..." and not p["db_saved"]:

                    vehicle_enter(p["plat"])
                    p["db_saved"]=True

                color=(0,255,0) if is_parking else (0,165,255)

                cv2.rectangle(frame,(x1,y1),(x2,y2),color,2)

                cv2.putText(
                    frame,
                    p["plat"],
                    (x1,y1-10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    color,
                    2
                )

                # =============================
                # TIMER
                # =============================

                if is_parking and p["park_start"]:

                    dur=int(time.time()-p["park_start"])

                    jam=dur//3600
                    menit=(dur%3600)//60
                    detik=dur%60

                    timer=f"{jam:02}:{menit:02}:{detik:02}"

                    cv2.putText(
                        frame,
                        timer,
                        (x1,y2+20),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0,255,0),
                        2
                    )

        # =============================
        # VEHICLE EXIT
        # =============================

        for tid in list(parking_data.keys()):

            if tid not in current_ids:

                plate=parking_data[tid]["plat"]

                if plate!="Scanning..." and parking_data[tid]["db_saved"]:

                    vehicle_exit(plate)

                del parking_data[tid]

        # Update frame for streaming
        frame_shared.latest_frame = frame.copy()

        if ENABLE_WINDOW:
            cv2.imshow("SMART PARKING AI",cv2.resize(frame,(960,540)))
            if cv2.waitKey(1)==27:
                break

    cv2.destroyAllWindows()

def start_flask():
    print(f"🌐 Starting Streaming Server on port {STREAM_PORT}...")
    app.run(host="0.0.0.0", port=STREAM_PORT, debug=False, use_reloader=False)

if __name__ == "__main__":
    # Start Flask in a background thread
    threading.Thread(target=start_flask, daemon=True).start()
    main()