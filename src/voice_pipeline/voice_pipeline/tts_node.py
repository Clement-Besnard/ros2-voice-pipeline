import queue, threading, time
import requests, sounddevice as sd
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String

RATE = 24000
PREBUFFER = int(RATE * 2 * 0.2)   # 200 ms de PCM int16 mono

class TTSNode(Node):
    def __init__(self):
        super().__init__('tts_node')
        self.url = self.declare_parameter('tts_url', 'http://10.8.0.1:8880').value
        self.voice = self.declare_parameter('voice', 'af_heart').value
        self.http = requests.Session()
        self.q = queue.Queue()
        self.speaking = self.create_publisher(Bool, 'tts_speaking', 10)
        self.create_subscription(String, 'llm_reply', lambda m: self.q.put(m.data), 10)
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        with sd.RawOutputStream(samplerate=RATE, channels=1, dtype='int16') as out:
            while rclpy.ok():
                self.say(self.q.get(), out)
                if self.q.empty():
                    time.sleep(0.3)
                    self.speaking.publish(Bool(data=False))

    def say(self, text, out):
        t0, first = time.perf_counter(), True
        try:
            with self.http.post(f'{self.url}/v1/audio/speech', stream=True, timeout=(5, 30), json={
                    'model': 'kokoro', 'voice': self.voice, 'input': text,
                    'response_format': 'pcm', 'stream': True}) as r:
                r.raise_for_status()
                self.speaking.publish(Bool(data=True))
                buf = b''
                for chunk in r.iter_content(4096):
                    buf += chunk
                    if first:
                        if len(buf) < PREBUFFER:      # on attend d'avoir ~200 ms d'avance
                            continue
                        self.get_logger().info(f'1er audio : {time.perf_counter() - t0:.2f}s')
                        first = False
                    n = len(buf) & ~1
                    out.write(buf[:n])
                    buf = buf[n:]
                if buf:                               # réponse plus courte que le pré-buffer
                    out.write(buf[:len(buf) & ~1])
        except Exception as e:
            self.get_logger().error(f'Erreur TTS : {e}')

def main():
    rclpy.init()
    rclpy.spin(TTSNode())
    rclpy.shutdown()