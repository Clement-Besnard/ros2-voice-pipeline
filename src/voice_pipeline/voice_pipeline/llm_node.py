import rclpy, requests
from rclpy.node import Node
from std_msgs.msg import String

# Sans ce prompt le modèle rédige 1300 tokens (31 s). Avec, une cinquantaine (1,8 s).
SYSTEM = ('Tu es un assistant vocal. Tes réponses sont lues à voix haute : '
          'réponds en français, en deux ou trois phrases maximum, sans listes, '
          'sans markdown et sans emoji.')

class LLMNode(Node):
    def __init__(self):
        super().__init__('llm_node')
        self.url = self.declare_parameter('ollama_url', 'http://10.8.0.1:11434').value
        self.model = self.declare_parameter('model', 'qwen3.8:27b').value
        self.system = self.declare_parameter('system_prompt', SYSTEM).value
        self.pub = self.create_publisher(String, 'llm_reply', 10)
        self.create_subscription(String, 'user_text', self.on_text, 10)
        self.get_logger().info(f'Modèle {self.model} sur {self.url}')

    def on_text(self, msg):
        self.get_logger().info(f'Question : {msg.data}')
        try:
            # timeout (connexion, lecture) : 120 en global tuait les réponses longues.
            r = requests.post(f'{self.url}/api/generate', timeout=(5, 120), json={
                'model': self.model, 'prompt': msg.data, 'system': self.system,
                'stream': False, 'think': False, 'keep_alive': '30m'})
            r.raise_for_status()
            reply = r.json()['response'].strip()
        except Exception as e:
            self.get_logger().error(f'Erreur Ollama : {e}')
            return
        self.get_logger().info(f'Réponse : {reply}')
        self.pub.publish(String(data=reply))

def main():
    rclpy.init()
    rclpy.spin(LLMNode())
    rclpy.shutdown()
