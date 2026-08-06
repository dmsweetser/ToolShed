import sounddevice as sd
import whisper
import pyperclip
import numpy as np
import keyboard


import threading
import time
import sys

SAMPLE_RATE = 16000
model = None
last_alt_press_time = 0
alt_press_count = 0
audio_buffer = []
recording = False
lock = threading.Lock()

def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"Status: {status}")
    with lock:
        if recording:
            audio_buffer.append(indata.copy())

def play_boop(freq, dur=100):
    duration = dur / 1000.0
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    tone = np.sin(2 * np.pi * freq * t)
    sd.play(tone, SAMPLE_RATE)
    sd.wait()

def toggle_recording():
    global recording, audio_buffer
    with lock:
        if not recording:
            recording = True
            audio_buffer = []
            play_boop(800, 100)
            print("Recording started. Speak into the microphone. Release the hotkey to stop and transcribe.")
        else:
            recording = False
            play_boop(600, 150)
            print("Recording stopped. Processing...")
            threading.Thread(target=process_audio, daemon=True).start()

def process_audio():
    global audio_buffer
    with lock:
        if not audio_buffer:
            print("[NO AUDIO RECORDED]")
            return
        data = np.concatenate(audio_buffer, axis=0).ravel().astype(np.float32)
        audio_buffer = []

    print("Transcribing...")
    result = model.transcribe(data, fp16=False)
    text = result["text"].strip()
    print(f"[TRANSCRIPT]: {text}")

    if text:
        pyperclip.copy(text)
        print(f"[COPIED TO CLIPBOARD]: {text}")
        play_boop(1200, 200)
    else:
        print("[TRANSCRIPTION EMPTY. NOTHING COPIED.]")

def on_alt_press(event):
    global last_alt_press_time, alt_press_count
    current_time = time.time()
    if current_time - last_alt_press_time < 0.5:
        alt_press_count += 1
    else:
        alt_press_count = 1
    last_alt_press_time = current_time

    if alt_press_count == 3:
        alt_press_count = 0
        toggle_recording()

def main():
    global model
    print("Loading Whisper model...")
    model = whisper.load_model("tiny")
    print("Model loaded. Press ALT three times to toggle recording.")

    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=audio_callback)
    stream.start()

    keyboard.on_press_key('alt', on_alt_press)
    print("Global ALT triple-press is now active. Keep this window open.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        stream.stop()
        stream.close()

if __name__ == "__main__":
    main()