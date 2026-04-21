import os
import time
from flask import Flask, jsonify, redirect, Response, request, abort
import mysql.connector
from functools import wraps
from dotenv import load_dotenv
from flasgger import Swagger
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# Security Config
ENGINE_API_KEY = os.getenv("ENGINE_API_KEY", "mata-plat-engine-secret").strip()

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check header x-api-key or query param api_key
        api_key = request.headers.get('x-api-key') or request.args.get('api_key')
        
        if not api_key or api_key != ENGINE_API_KEY:
            return jsonify({"error": "Unauthorized. Please provide a valid API Key."}), 401
        return f(*args, **kwargs)
    return decorated_function

# Swagger Configuration
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec_v1',
            "route": '/api/v1/spec.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
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
        "description": "API dokumentasi untuk engine sistem parkir berbasis AI. Seluruh endpoint dilindungi oleh x-api-key.",
        "version": "1.1.0",
        "contact": {
            "name": "mikeu-dev",
            "url": "https://mikeudev.my.id",
        }
    },
    "securityDefinitions": {
        "APIKeyHeader": {
            "type": "apiKey",
            "name": "x-api-key",
            "in": "header"
        }
    },
    "security": [
        {
            "APIKeyHeader": []
        }
    ],
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
@require_api_key
def logs():
    """
    Get Parking Logs (Secured)
    ---
    security:
      - APIKeyHeader: []
    responses:
      200:
        description: A list of parking logs from the database
        schema:
          type: array
          items:
            type: object
            properties:
              id: {type: integer}
              license_plate: {type: string}
              action: {type: string}
              timestamp: {type: string, format: date-time}
      401:
        description: Unauthorized
    """
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 100")
    data = cursor.fetchall()

    return jsonify(data)

def gen_frames(gate_id):
    last_timestamp = 0
    gate_id = int(gate_id)
    
    while True:
        # Ambil timestamp terbaru dari engine
        current_timestamp = frame_shared.frame_timestamps.get(gate_id, 0)
        
        if current_timestamp > last_timestamp:
            # Hanya ambil bytes jika timestamp berubah (lebih efisien CPU)
            frame_bytes = frame_shared.latest_frames.get(gate_id)
            
            if frame_bytes is not None:
                last_timestamp = current_timestamp
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            else:
                time.sleep(0.01)
        else:
            # Jeda kecil jika belum ada frame baru (sekitar 60 FPS check)
            time.sleep(0.016)

@app.route("/video_feed/<int:gate_id>")
@require_api_key
def video_feed(gate_id):
    """
    MJPEG Video Stream per Gate (Secured)
    ---
    parameters:
      - name: gate_id
        in: path
        type: integer
        required: true
      - name: api_key
        in: query
        type: string
        description: API Key (untuk akses via browser/img tag)
    security:
      - APIKeyHeader: []
    responses:
      200:
        description: Continuous MJPEG stream
      401:
        description: Unauthorized
    """
    return Response(gen_frames(gate_id), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("STREAM_PORT", 5000)), debug=os.getenv("FLASK_DEBUG", "True") == "True")