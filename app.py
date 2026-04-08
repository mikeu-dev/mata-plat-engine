import os
import time
from flask import Flask, jsonify, render_template, Response
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", ""),
        database=os.getenv("DB_NAME", "parking_db")
    )

import frame_shared
import cv2

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/logs")
def logs():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM logs ORDER BY id DESC")
    data = cursor.fetchall()

    return jsonify(data)

def gen_frames():
    while True:
        if frame_shared.latest_frame is not None:
            # Encode frame sebagai JPEG
            ret, buffer = cv2.imencode('.jpg', frame_shared.latest_frame)
            if not ret:
                continue
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            time.sleep(0.1)

@app.route("/video_feed")
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "True") == "True")