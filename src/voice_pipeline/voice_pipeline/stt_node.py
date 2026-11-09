import collections, io, queue, threading, time, wave
import numpy as np, requests, sounddevice as sd
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

RATE = 16000                       # Whisper attend du 16 kHz mono
BLOCK_MS = 30
BLOCK = RATE * BLOCK_MS // 1000
# Sorties typiques de Whisper sur du bruit ou du silence
HALLUCINATIONS = {'', '.'}

class STTNode(Node):
    def __init__(self):
        super().__init__('stt_node')
        p = lambda name, val: self.declare_parameter(name, val).value
        self.url = p('stt_url', 'http://10.8.0.1:8001')
        self.model = p('model', 'Systran/faster-distil-whisper-large-v3')
        self.lang = p('language', 'en')
        self.factor = p('threshold_factor', 3.0)     # seuil = bruit ambiant × facteur
        self.min_thr = p('min_threshold', 300.0)     # plancher du seuil (RMS int16)
        self.silence_blocks = p('silence_ms', 600) // BLOCK_MS   # silence = fin de phrase
        self.min_blocks = p('min_speech_ms', 300) // BLOCK_MS    # ignore les bruits brefs
        self.max_blocks = p('max_speech_ms', 15000) // BLOCK_MS
        self.pre_blocks = p('preroll_ms', 300) // BLOCK_MS       # évite de couper le début
        device = p('device', -1)                     # -1 = micro par défaut

        self.pub = self.create_publisher(String, 'user_text', 10)
        self.http = requests.Session()
        self.q = queue.Queue()
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype='int16',
                                     blocksize=BLOCK, callback=self.on_audio,
                                     device=None if device < 0 else device)
        self.stream.start()
        threading.Thread(target=self.loop, daemon=True).start()

    def on_audio(self, indata, frames, t, status):
        self.q.put(indata[:, 0].copy())   # callback audio : ne rien faire de lourd ici

    @staticmethod
    def rms(b):
        return float(np.sqrt(np.mean(b.astype(np.float32) ** 2)))

    def calibrate(self):
        self.get_logger().info('Calibration du bruit ambiant (1 s), silence…')
        levels = [self.rms(self.q.get()) for _ in range(1000 // BLOCK_MS)]
        noise = float(np.median(levels))
        self.thr = max(noise * self.factor, self.min_thr)
        self.get_logger().info(f'Bruit {noise:.0f} → seuil {self.thr:.0f}. Prêt.')

    def loop(self):
        self.calibrate()
        pre = collections.deque(maxlen=self.pre_blocks)
        speech, silent, loud = [], 0, 0
        while rclpy.ok():
            b = self.q.get()
            active = self.rms(b) > self.thr
            if not speech:                       # en attente de parole
                pre.append(b)
                loud = loud + 1 if active else 0
                if loud >= 3:                    # 90 ms au-dessus du seuil = début
                    speech, silent = list(pre), 0
                continue
            speech.append(b)                     # en cours de phrase
            silent = 0 if active else silent + 1
            if silent >= self.silence_blocks or len(speech) >= self.max_blocks:
                audio, n_voiced = np.concatenate(speech), len(speech) - silent
                speech, loud = [], 0
                pre.clear()
                if n_voiced >= self.min_blocks:
                    self.transcribe(audio)

    def transcribe(self, audio):
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(audio.tobytes())
        t0 = time.perf_counter()
        try:
            r = self.http.post(f'{self.url}/v1/audio/transcriptions', timeout=(5, 30),
                               files={'file': ('speech.wav', buf.getvalue(), 'audio/wav')},
                               data={'model': self.model, 'language': self.lang})
            r.raise_for_status()
            text = r.json()['text'].strip()
        except Exception as e:
            self.get_logger().error(f'Erreur STT : {e}')
            return
        dt = time.perf_counter() - t0
        if text.lower() in HALLUCINATIONS:
            self.get_logger().info(f'Ignoré : "{text}" ({dt:.2f}s)')
            return
        self.get_logger().info(f'{len(audio) / RATE:.1f}s audio → {dt:.2f}s : {text}')
        self.pub.publish(String(data=text))

def main():
    rclpy.init()
    node = STTNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.stream.stop()
    node.destroy_node()
    rclpy.try_shutdown()