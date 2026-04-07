import numpy as np
import onnxruntime as ort
import librosa
import gradio as gr
from groq import Groq
import os

# ---------- CONFIG ----------
MODEL_ONNX = "titanet_small_encoder.onnx"
# PENTING: Gunakan API Key baru kamu di sini
API_KEY = ""

# ---------- INITIALIZATION ----------
client = Groq(api_key=API_KEY)
# Inisialisasi ONNX dengan penanganan error
try:
    session = ort.InferenceSession(MODEL_ONNX)
    print("✅ Model ONNX berhasil dimuat.")
except Exception as e:
    print(f"❌ Gagal memuat model ONNX: {e}")

def extract_embedding(audio_chunk):
    # TitaNet ONNX biasanya mengharapkan input [1, durasi_sampel]
    audio_signal = np.expand_dims(audio_chunk.astype(np.float32), axis=0)
    length = np.array([audio_signal.shape[1]], dtype=np.int64)
    
    outputs = session.run(None, {
        "audio_signal": audio_signal, 
        "length": length
    })
    
    emb = outputs[0][0]
    return emb / np.linalg.norm(emb)

def process_diarization(input_audio_path):
    if not input_audio_path:
        return "Mohon upload file audio."

    try:
        # 1. Load Audio
        # librosa.load akan otomatis menggunakan skrip internal Gradio 
        # untuk menangani file sementara.
        audio, sr = librosa.load(input_audio_path, sr=16000)
        
        # 2. Transkripsi via Groq
        with open(input_audio_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                file=f,
                model="whisper-large-v3",
                response_format="verbose_json"
            )
        
        # 3. Proses Identifikasi Speaker
        results = []
        speaker_embeddings = []
        THRESHOLD = 0.70 # Turunkan sedikit agar lebih fleksibel

        for seg in transcript.segments:
            start_idx = int(seg["start"] * sr)
            end_idx = int(seg["end"] * sr)
            chunk = audio[start_idx:end_idx]

            if len(chunk) < 1600: # Abaikan jika < 0.1 detik
                continue

            emb = extract_embedding(chunk)
            
            speaker_id = None
            max_sim = -1
            best_idx = -1

            for i, saved_emb in enumerate(speaker_embeddings):
                sim = np.dot(emb, saved_emb)
                if sim > max_sim:
                    max_sim = sim
                    best_idx = i

            if max_sim > THRESHOLD:
                speaker_id = best_idx
            else:
                speaker_embeddings.append(emb)
                speaker_id = len(speaker_embeddings) - 1

            results.append(f"**Speaker {speaker_id + 1}**: {seg['text']}")

        return "\n\n".join(results)

    except Exception as e:
        return f"Terjadi kesalahan teknis: {str(e)}\n\n*Catatan: Jika error NoBackend, pastikan file yang diupload adalah format .wav atau install FFmpeg.*"

# ---------- UI GRADIO ----------
with gr.Blocks(title="AI Interview Diarization") as demo:
    gr.Markdown("# 🎙️ Transkripsi & Pemisahan Pembicara")
    gr.Markdown("Upload file rekaman wawancara kamu (MP3/WAV). Sistem akan mendeteksi siapa yang bicara.")
    
    with gr.Row():
        audio_input = gr.Audio(label="File Audio", type="filepath")
    
    with gr.Row():
        btn = gr.Button("Mulai Proses", variant="primary")
    
    output_text = gr.Markdown(label="Hasil")

    btn.click(fn=process_diarization, inputs=audio_input, outputs=output_text)

if __name__ == "__main__":
    demo.launch(share=True) # share=True akan memberikan link public sementara