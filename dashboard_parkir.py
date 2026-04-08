import os
import streamlit as st
import pandas as pd
import time
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

db_user = os.getenv("DB_USER", "root")
db_pass = os.getenv("DB_PASS", "")
db_host = os.getenv("DB_HOST", "localhost")
db_name = os.getenv("DB_NAME", "parking_db")

engine=create_engine(f"mysql+mysqlconnector://{db_user}:{db_pass}@{db_host}/{db_name}")

st.set_page_config(page_title="Smart Parking Dashboard",layout="wide")

st.title("🚗 Smart Parking AI Dashboard")

def get_data():
    try:
        return pd.read_sql("SELECT * FROM logs ORDER BY id DESC",engine)
    except:
        return pd.DataFrame()

placeholder=st.empty()

while True:

    df=get_data()

    with placeholder.container():

        if not df.empty:

            m1,m2,m3=st.columns(3)

            m1.metric("Total Kendaraan",len(df))
            m2.metric("Sedang Parkir",len(df[df['time_out'].isna()]))
            m3.metric("Total Pendapatan",f"Rp {int(df['total_bill'].sum() or 0):,}")

            col1,col2=st.columns([2,1])

            with col1:
                st.subheader("Data Parkir")
                st.dataframe(df,use_container_width=True)

            with col2:
                st.subheader("Jenis Kendaraan")
                st.bar_chart(df['vehicle_type'].value_counts())

        else:
            st.info("Menunggu data dari engine...")

    time.sleep(2)