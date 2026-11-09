# bench.py — lancer avec llm_node déjà démarré
import time, requests, rclpy
from rclpy.node import Node
from std_msgs.msg import String

URL, MODEL = 'http://10.8.0.1:11434', 'qwen3:8b'
SYSTEM = ('You are a voice assistant. Your responses are read aloud: '
          'answer in English, in two or three sentences at most, with no lists, '
          'no markdown, and no emoji.')
QUESTIONS = [
    'What is the capital of France?',
    'Explain briefly how a PID controller works and why the derivative term helps.',
    'I am building a six-axis robotic arm. What are the main difficulties in computing '
    'its inverse kinematics, and how would you approach them in practice?',
]
QUIET = 1.5  # s sans nouveau message = réponse terminée (gère le node en streaming)

def direct(s, q):
    t = time.perf_counter()
    r = s.post(f'{URL}/api/generate', timeout=(5, 120), json={
        'model': MODEL, 'prompt': q, 'system': SYSTEM,
        'stream': False, 'think': False, 'keep_alive': '30m'})
    r.raise_for_status()
    d = r.json()
    gen, gs = d.get('eval_count', 0), d.get('eval_duration', 1) / 1e9
    print(f'  direct  : {time.perf_counter() - t:.2f}s | '
          f'prompt {d.get("prompt_eval_count", 0)} tok '
          f'{d.get("prompt_eval_duration", 0) / 1e9:.2f}s | '
          f'gen {gen} tok à {gen / gs:.0f} tok/s')

class Bench(Node):
    def __init__(self):
        super().__init__('bench')
        self.pub = self.create_publisher(String, 'user_text', 10)
        self.create_subscription(String, 'llm_reply', self.on_reply, 10)
        self.t0 = self.first = self.last = None

    def ask(self, q):
        self.first = self.last = None
        self.t0 = time.perf_counter()
        self.pub.publish(String(data=q))

    def on_reply(self, msg):
        now = time.perf_counter()
        self.first = self.first or now
        self.last = now

def main():
    rclpy.init()
    n = Bench()
    while n.pub.get_subscription_count() == 0:
        rclpy.spin_once(n, timeout_sec=0.05)
    s = requests.Session()
    s.post(f'{URL}/api/generate', json={'model': MODEL, 'keep_alive': '30m'})  # warm-up

    for q in QUESTIONS:
        print(f'\n« {q[:70]}{"…" if len(q) > 70 else ""} »')
        direct(s, q)
        n.ask(q)
        while True:
            rclpy.spin_once(n, timeout_sec=0.05)
            now = time.perf_counter()
            if n.last and now - n.last > QUIET:
                break
            if now - n.t0 > 120:
                print('  via ROS : timeout')
                break
        if n.first:
            print(f'  via ROS : 1er message {n.first - n.t0:.2f}s | '
                  f'dernier {n.last - n.t0:.2f}s')
    rclpy.shutdown()

if __name__ == '__main__':
    main()