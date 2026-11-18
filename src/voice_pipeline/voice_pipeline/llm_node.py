import json, time, uuid

import rclpy, requests
from rclpy.node import Node
from std_msgs.msg import String

# Le modèle, son adresse et le prompt système vivent côté n8n, plus ici.

class LLMNode(Node):
    def __init__(self):
        super().__init__('llm_node')
        self.url = self.declare_parameter('n8n_url', 'http://10.8.0.1:5678/webhook/llm').value
        # Préfixe de la clé de mémoire n8n. Le suffixe change à chaque nouvelle
        # conversation, cf. on_text.
        self.base = self.declare_parameter('session_id', 'ros-voice').value
        # Silence au-delà duquel la conversation suivante repart vierge.
        self.idle = self.declare_parameter('session_timeout', 300.0).value
        self.session = self.last = None
        self.pub = self.create_publisher(String, 'llm_reply', 10)
        self.create_subscription(String, 'user_text', self.on_text, 10)
        self.get_logger().info(f'Agent n8n sur {self.url} (sessions {self.base}-*)')

    def on_text(self, msg):
        self.get_logger().info(f'Question : {msg.data}')
        # Une conversation se termine par le silence : passé self.idle sans rien
        # entendre, on change de clé et n8n repart sur une mémoire vide.
        now = time.monotonic()
        if self.last is None or now - self.last > self.idle:
            self.session = f'{self.base}-{uuid.uuid4().hex[:8]}'
            self.get_logger().info(f'Nouvelle conversation : {self.session}')
        self.last = now
        reply = ''
        try:
            # timeout (connexion, lecture) : en streaming le second porte sur
            # l'attente entre deux lignes, pas sur la réponse entière.
            r = requests.post(self.url, timeout=(5, 120), stream=True, json={
                'question': msg.data, 'session_id': self.session})
            r.raise_for_status()
            # NDJSON, un objet par ligne. n8n répond 200 même quand l'agent
            # échoue : l'erreur arrive dans le flux, pas dans le code HTTP.
            for line in r.iter_lines(decode_unicode=True):
                ev = json.loads(line) if line.strip() else {}
                if ev.get('type') == 'error':
                    raise RuntimeError(ev['content'])
                if ev.get('type') == 'item':
                    reply += ev['content']
        except Exception as e:
            self.get_logger().error(f'Erreur n8n : {e}')
            return
        reply = reply.strip()
        self.get_logger().info(f'Réponse : {reply}')
        self.pub.publish(String(data=reply))

def main():
    rclpy.init()
    rclpy.spin(LLMNode())
    rclpy.shutdown()
