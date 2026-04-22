import threading

# Dictionary untuk menampung frame dari banyak kamera sekaligus (key: gate_id)
latest_frames = {}

# Dictionary untuk melacak kapan terakhir kali frame diperbarui (key: gate_id)
frame_timestamps = {}

# Event untuk mentrigger reload konfigurasi dari dashboard
reload_event = threading.Event()
