import os
import time
from flask import Flask, jsonify, redirect, Response
import mysql.connector
from dotenv import load_dotenv
from flasgger import Swagger
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# Swagger Configuration
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec_v1',
            "route": '/api/v1/spec.json',
            "rule_filter": lambda rule: True,  # all in
            "model_filter": lambda tag: True,  # all in
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api/v1/docs"
}

swagger_template = {
    "swagger": "2.0",
    "info": {
        "title": "Mata Plat Engine API",
        "description": "API dokumentasi untuk engine sistem parkir berbasis AI.",
        "version": "1.0.0",
        "contact": {
            "name": "mikeu-dev",
            "url": "https://mikeudev.my.id",
        }
    },
    "schemes": [
        "http",
        "https"
    ]
}

swagger = Swagger(app, config=swagger_config, template=swagger_template)

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
    """
    Redirect to API documentation
    ---
    responses:
      302:
        description: Redirects to /api/v1/docs
    """
    return redirect("/api/v1/docs")

@app.route("/api/logs")
def logs():
    """
    Get Parking Logs
    ---
    responses:
      200:
        description: A list of parking logs from the database
        schema:
          type: array
          items:
            type: object
            properties:
              id:
                type: integer
              license_plate:
                type: string
              action:
                type: string
    """
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM logs ORDER BY id DESC")
    data = cursor.fetchall()

    return jsonify(data)

def gen_frames(gate_id):
    last_sent_bytes = None
    
    while True:
        # Ambil frame bytes yang sudah di-encode oleh engine
        frame_bytes = frame_shared.latest_frames.get(gate_id)
        
        if frame_bytes is not None:
            # Hindari mengirim data yang sama jika engine belum update
            # Gunakan == untuk cek isi bytes (nilai), bukan is (identitas memori)
            if frame_bytes == last_sent_bytes:
                time.sleep(0.033) # Jeda sekitar 30 FPS untuk menghemat bandwidth
                continue
                
            last_sent_bytes = frame_bytes
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            time.sleep(0.1)

@app.route("/video_feed/<int:gate_id>")
def video_feed(gate_id):
    """
    MJPEG Video Stream per Gate
    ---
    responses:
      200:
        description: Continuous MJPEG stream of the specific camera frame
    """
    return Response(gen_frames(gate_id), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "True") == "True")