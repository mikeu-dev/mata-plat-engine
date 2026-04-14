# frame_shared.py
# Modul sederhana untuk berbagi frame antara engine pemroses dan server streaming

# Dictionary untuk menampung frame dari banyak kamera sekaligus (key: gate_id)
latest_frames = {}
