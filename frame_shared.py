# frame_shared.py
# Modul sederhana untuk berbagi frame antara engine pemroses dan server streaming

# Dictionary untuk menampung frame dari banyak kamera sekaligus (key: gate_id)
latest_frames = {}

# Dictionary untuk melacak kapan terakhir kali frame diperbarui (key: gate_id)
# Digunakan untuk efisiensi pengecekan di Flask agar tidak perlu membandingkan bytes array
frame_timestamps = {}
