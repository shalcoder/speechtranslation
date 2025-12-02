import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode, AudioProcessorBase
import av
import numpy as np
import threading
import queue
import time
import azure.cognitiveservices.speech as speechsdk
from scripts.backend.ultraaudio.config import AZURE_KEY, AZURE_LOCATION

from scripts.backend.db import DatabaseManager

class AzureAudioProcessor(AudioProcessorBase):
    def __init__(self):
        self.audio_queue = queue.Queue()
        # Configure Azure Stream Format explicitly (16kHz, 16-bit, Mono)
        self.azure_format = speechsdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
        self.stream = speechsdk.audio.PushAudioInputStream(stream_format=self.azure_format)
        self.is_running = True
        # Resampler
        self.resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
        
        # Start processing thread to unblock recv
        self.worker_thread = threading.Thread(target=self._process_audio, daemon=True)
        self.worker_thread.start()
        
    def recv(self, frame: av.AudioFrame) -> av.AudioFrame:
        """Correct method name for audio processing"""
        if self.is_running:
            # Enqueue frame for processing
            self.audio_queue.put(frame)
            print(f"[RemoteMeeting] Audio frame received: {frame.samples} samples")
        return frame

    def _process_audio(self):
        while self.is_running:
            try:
                frame = self.audio_queue.get(timeout=1)
                # Resample and write to Azure
                resampled_frames = self.resampler.resample(frame)
                for resampled_frame in resampled_frames:
                    audio_bytes = resampled_frame.to_ndarray().tobytes()
                    self.stream.write(audio_bytes)
                    print(f"[RemoteMeeting] Sent {len(audio_bytes)} bytes to Azure")
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[RemoteMeeting] Audio processing error: {e}")

    def stop(self):
        self.is_running = False
        self.stream.close()

def start_azure_recognition(audio_stream, source_lang, target_lang, result_queue):
    try:
        print(f"[RemoteMeeting] Starting Azure recognition: {source_lang} -> {target_lang}")
        
        speech_config = speechsdk.translation.SpeechTranslationConfig(
            subscription=AZURE_KEY, 
            region=AZURE_LOCATION
        )
        speech_config.speech_recognition_language = source_lang
        speech_config.add_target_language(target_lang)
        
        audio_config = speechsdk.audio.AudioConfig(stream=audio_stream) 
        
        recognizer = speechsdk.translation.TranslationRecognizer(
            translation_config=speech_config, 
            audio_config=audio_config
        )

        def result_callback(evt):
            print(f"[RemoteMeeting] Recognition event: {evt.result.reason}")
            if evt.result.reason == speechsdk.ResultReason.TranslatedSpeech:
                trans = evt.result.translations.get(target_lang, "")
                print(f"[RemoteMeeting] Original: {evt.result.text}")
                print(f"[RemoteMeeting] Translated: {trans}")
                if evt.result.text and trans:
                    result_queue.put({
                        "original": evt.result.text,
                        "translated": trans,
                        "timestamp": time.strftime("%H:%M:%S")
                    })

        def canceled_callback(evt):
            print(f"[RemoteMeeting] Recognition canceled: {evt.reason}")
            if evt.reason == speechsdk.CancellationReason.Error:
                print(f"[RemoteMeeting] Error details: {evt.error_details}")
                result_queue.put({
                    "original": f"ERROR: {evt.error_details}",
                    "translated": "Recognition failed. Check Azure credentials.",
                    "timestamp": time.strftime("%H:%M:%S")
                })

        recognizer.recognized.connect(result_callback)
        recognizer.canceled.connect(canceled_callback)
        
        print("[RemoteMeeting] Starting continuous recognition...")
        recognizer.start_continuous_recognition()
        
        while True:
            time.sleep(0.5)
            
    except Exception as e:
        print(f"[RemoteMeeting] Azure Error: {e}")
        result_queue.put({
            "original": f"EXCEPTION: {str(e)}",
            "translated": "Azure connection failed. Check credentials.",
            "timestamp": time.strftime("%H:%M:%S")
        })


def render_remote_meeting(
    source_lang_name,
    target_lang_name,
    source_lang_code,
    target_lang_code
):
    st.markdown("## 🤝 Remote Meeting & Translation")
    st.caption("Join a shared room to communicate with others. Your speech will be translated and broadcasted.")

    # Use SQLite DB Manager
    db = DatabaseManager()

    # User Settings
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        username = st.text_input("Your Name", value="User", key="user_name")
    with c2:
        room_id = st.text_input("Room ID", value="General", help="Users in the same room see each other's messages.")
    with c3:
        st.info(f"Translating **{source_lang_name}** ➝ **{target_lang_name}**")

    # Custom CSS to resize video
    st.markdown("""
        <style>
        .stWebRtc video {
            max-width: 50% !important;
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
            border: 2px solid rgba(91, 86, 233, 0.3);
        }
        </style>
    """, unsafe_allow_html=True)
    
    # WebRTC Streamer with enhanced quality settings
    ctx = webrtc_streamer(
        key="remote-meeting-shared",
        mode=WebRtcMode.SENDRECV,
        rtc_configuration={
            "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
        },
        media_stream_constraints={
            "video": {
                "width": {"min": 1280, "ideal": 1280, "max": 1920},
                "height": {"min": 720, "ideal": 720, "max": 1080},
                "frameRate": {"ideal": 30, "max": 30}
            },
            "audio": {
                "echoCancellation": True,
                "noiseSuppression": True,
                "autoGainControl": True,
                "sampleRate": 48000,
                "channelCount": 1
            }
        },
        audio_processor_factory=AzureAudioProcessor,
        async_processing=True,
    )

    # Display Translations
    st.markdown("### 💬 Room Transcript")
    chat_container = st.container(height=400, border=True)
    
    if ctx.audio_processor:
        # Start Azure Thread if needed
        if not hasattr(ctx.audio_processor, 'azure_thread_started'):
            ctx.audio_processor.result_queue = queue.Queue()
            ctx.audio_processor.azure_thread_started = True
            
            t = threading.Thread(
                target=start_azure_recognition,
                args=(
                    ctx.audio_processor.stream, 
                    source_lang_code, 
                    target_lang_code, 
                    ctx.audio_processor.result_queue
                ),
                daemon=True
            )
            t.start()
            
        # Process new local messages and push to DB
        while not ctx.audio_processor.result_queue.empty():
            msg = ctx.audio_processor.result_queue.get()
            # Save to DB
            db.add_message(
                room_id, 
                username, 
                msg['original'], 
                msg['translated'], 
                source_lang_code
            )
        
    # Always display messages from the DB
    messages = db.get_messages(room_id)
    
    with chat_container:
        if not messages:
            st.info(f"Room '{room_id}' is empty. Start speaking to post messages.")
        
        # Messages come oldest first from DB helper? 
        # I implemented get_messages to return rows[::-1] which is oldest first.
        # Let's verify tuple unpacking: (user, original, translated, timestamp, lang)
        
        for msg in messages:
            # msg is a tuple: (user, original, translated, timestamp, lang)
            user, original, translated, timestamp, lang = msg
            
            is_me = (user == username)
            align = "right" if is_me else "left"
            
            # Enhanced UI
            bg_color = "linear-gradient(135deg, #5B56E9 0%, #7B6AFF 100%)" if is_me else "rgba(255, 255, 255, 0.1)"
            text_align = "right" if is_me else "left"
            
            st.markdown(
                f"""
                <div style="display: flex; justify-content: {align}; margin-bottom: 15px;">
                    <div style="
                        background: {bg_color}; 
                        color: #fff; 
                        padding: 12px 18px; 
                        border-radius: 16px; 
                        border-bottom-{align}-radius: 2px;
                        max-width: 75%;
                        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
                    ">
                        <div style="font-size: 0.75rem; opacity: 0.8; margin-bottom: 4px; text-align: {text_align};">
                            <strong>{user}</strong> • {timestamp}
                        </div>
                        <div style="font-size: 0.9rem; margin-bottom: 6px; font-style: italic; opacity: 0.9;">
                            "{original}"
                        </div>
                        <div style="font-size: 1.1rem; font-weight: 600; border-top: 1px solid rgba(255,255,255,0.2); padding-top: 6px;">
                            {translated}
                        </div>
                    </div>
                </div>
                """, 
                unsafe_allow_html=True
            )
    
    # Auto-refresh
    if ctx.state.playing:
        time.sleep(1)
        st.rerun()
    
    # Download Transcript Button
    st.markdown("---")
    if messages:
        import csv
        import io
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['User', 'Original Text', 'Translated Text', 'Timestamp', 'Language'])
        
        # Write messages
        for msg in messages:
            user, original, translated, timestamp, lang = msg
            writer.writerow([user, original, translated, timestamp, lang])
        
        csv_content = output.getvalue()
        output.close()
        
        # Encode with UTF-8 BOM for Excel compatibility
        csv_bytes = csv_content.encode('utf-8-sig')
        
        st.download_button(
            label=f"📥 Download Transcript (CSV) - {len(messages)} messages",
            data=csv_bytes,
            file_name=f"meeting_transcript_{room_id}_{time.strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            help="Download conversation transcript with UTF-8 encoding"
        )

