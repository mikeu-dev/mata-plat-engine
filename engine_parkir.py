import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

import cv2
import numpy as np
import time
import threading
import re
from queue import Queue
from ultralytics import YOLO
from paddleocr import PaddleOCR
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

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
# MODEL GPU
# =============================

model_vehicle = YOLO("yolov8l.pt")
model_vehicle.to("cuda")

model_plate = YOLO("license_plate_detector.pt")
model_plate.to("cuda")

ocr = PaddleOCR(lang="en")

# =============================
# ASYNC CAMERA
# =============================

class VideoCaptureAsync:

    def __init__(self,src):

        self.cap=cv2.VideoCapture(src,cv2.CAP_FFMPEG)
        self.ret,self.frame=self.cap.read()

        self.running=True

        threading.Thread(target=self.update,daemon=True).start()

    def update(self):

        while self.running:

            ret,frame=self.cap.read()

            if ret:
                self.ret=ret
                self.frame=frame

    def read(self):

        return self.ret,self.frame

# =============================
# DATABASE FUNCTIONS
# =============================

def vehicle_enter(plate):

    cursor.execute(
        "INSERT INTO logs (plate,time_in) VALUES (%s,NOW())",
        (plate,)
    )

    db.commit()

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

# =============================
# OCR SYSTEM
# =============================

ocr_queue=Queue()
parking_data={}

def preprocess_plate(img):

    img=cv2.resize(img,None,fx=2,fy=2)

    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)

    gray=cv2.bilateralFilter(gray,11,17,17)

    gray=cv2.adaptiveThreshold(
        gray,255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,11,2
    )

    return gray

def validate_plate(text):

    text=text.replace(" ","").upper()

    if re.match(PLATE_REGEX,text):
        return text

    return None

# =============================
# OCR WORKER
# =============================

def ocr_worker():

    while True:

        tid,crop=ocr_queue.get()

        try:

            img=preprocess_plate(crop)

            result=ocr.ocr(img)

            plate=""

            if result:
                for line in result:
                    for word in line:
                        plate+=word[1][0]

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

    cap=VideoCaptureAsync(RTSP_URL)

    frame_count=0

    while True:

        ret,frame=cap.read()

        if not ret:
            continue

        frame_count+=1

        if frame_count % FRAME_SKIP !=0:
            continue

        results=model_vehicle.track(
            frame,
            persist=True,
            conf=0.35,
            imgsz=960,
            tracker="bytetrack.yaml",
            device=0,
            verbose=False
        )

        current_ids=set()

        if results[0].boxes.id is not None:

            boxes=results[0].boxes.xyxy.cpu().numpy().astype(int)
            ids=results[0].boxes.id.cpu().numpy().astype(int)
            clss=results[0].boxes.cls.cpu().numpy().astype(int)

            for box,tid,cls_idx in zip(boxes,ids,clss):

                if cls_idx not in VEHICLE_CLASSES:
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

                is_parking = p["state"]=="stopped"

                # =============================
                # OCR
                # =============================

                if is_parking and time.time()-p["ocr_time"]>2:

                    roi=frame[y1:y2,x1:x2]

                    plate_res=model_plate.predict(
                        roi,
                        conf=0.45,
                        imgsz=416,
                        device=0,
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

        cv2.imshow("SMART PARKING AI",cv2.resize(frame,(960,540)))

        if cv2.waitKey(1)==27:
            break

    cv2.destroyAllWindows()

main()