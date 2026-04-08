import os
from flask import Flask, jsonify, render_template
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

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "True") == "True")