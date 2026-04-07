import streamlit as st
import pandas as pd
import time
from datetime import datetime
from sqlalchemy import create_engine

# =============================
# KONFIGURASI DATABASE MYSQL
# =============================
DB_USER = "root"
DB_PASS = "" # Isi jika ada password
DB_HOST = "localhost"
DB_NAME = "parking_db"

# Engine SQLAlchemy untuk MySQL
engine = create_engine(f"mysql+mysqlconnector://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}")

# Konfigurasi Halaman Streamlit
st.set_page_config(
    page_title="Smart Parking Dashboard",
    page_icon="🚗",
    layout="wide"
)

def get_data():
    try:
        # Mengambil data dari tabel logs di MySQL
        query = "SELECT * FROM logs ORDER BY id DESC"
        df = pd.read_sql(query, engine)
        return df
    except Exception as e:
        # Menangani jika tabel belum terbuat
        if "doesn't exist" in str(e).lower():
            return pd.DataFrame() 
        st.error(f"Gagal memuat database MySQL: {e}")
        return pd.DataFrame()

# Sidebar
st.sidebar.title("🚀 Control Panel")
refresh_rate = st.sidebar.slider("Auto Refresh (detik)", 1, 10, 2)
st.sidebar.markdown("---")
st.sidebar.info("Dashboard terhubung ke database MySQL `parking_db`.")

# Header
st.title("📊 Real-Time Smart Parking Monitoring")
st.write(f"Status Server: ✅ Connected | Last Update: {datetime.now().strftime('%H:%M:%S')}")
st.markdown("---")

# Placeholder untuk konten dinamis
placeholder = st.empty()

while True:
    df = get_data()
    
    with placeholder.container():
        if not df.empty:
            # --- METRIK UTAMA ---
            m1, m2, m3, m4 = st.columns(4)
            
            total_kendaraan = len(df)
            # Menghitung kendaraan yang belum keluar (time_out NULL)
            sedang_parkir = len(df[df['time_out'].isna()])
            total_pendapatan = df['total_bill'].sum()
            
            m1.metric("Total Kendaraan (Log)", f"{total_kendaraan}")
            m2.metric("Sedang Parkir", f"{sedang_parkir}", delta=f"{sedang_parkir} Aktif")
            m3.metric("Total Pendapatan", f"Rp {int(total_pendapatan):,}")
            m4.metric("Engine", "YOLOv8 + Llama-4")

            # --- TAMPILAN UTAMA ---
            col_tabel, col_grafik = st.columns([2, 1])

            with col_tabel:
                st.subheader("📝 Riwayat Transaksi")
                # Format tampilan tabel agar lebih rapi
                st.dataframe(
                    df.style.highlight_null(color="#333333"), 
                    use_container_width=True, 
                    height=450
                )

            with col_grafik:
                st.subheader("📈 Komposisi Kendaraan")
                if 'vehicle_type' in df.columns:
                    type_counts = df['vehicle_type'].value_counts()
                    st.bar_chart(type_counts)
                
                st.subheader("ℹ️ Informasi Sistem")
                st.info(f"""
                - **Sisa Slot:** {max(0, 50 - sedang_parkir)}
                - **Tarif:** Rp {5000}/jam
                - **DB Source:** MySQL (parking_db)
                """)
        else:
            st.warning("⚠️ Menunggu data dari script deteksi... Pastikan tabel 'logs' sudah terisi di MySQL.")
            st.image("https://via.placeholder.com/800x400.png?text=Waiting+for+Live+Feed+from+YOLOv8", use_column_width=True)

    time.sleep(refresh_rate)