from flask import Flask, jsonify, render_template
import mysql.connector

app = Flask(__name__)

def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="parking_db"
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
    app.run(debug=True)