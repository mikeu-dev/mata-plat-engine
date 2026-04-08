import uuid

def get_hardware_id():
    # Mengambil MAC Address sebagai identitas unik integer, lalu diubah ke format Hex
    mac_num = uuid.getnode()
    mac_hex = ':'.join(['{:02x}'.format((mac_num >> i) & 0xff) for i in range(0, 8*6, 8)][::-1])
    return mac_hex

if __name__ == "__main__":
    print(f"DEBUG: Hardware ID (MAC) terdeteksi: {get_hardware_id()}")
