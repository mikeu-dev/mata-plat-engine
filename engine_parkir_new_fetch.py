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
