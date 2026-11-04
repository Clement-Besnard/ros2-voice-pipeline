import rclpy, requests
from rclpy.node import Node
from std_msgs.msg import String

class LLMNode(Node):
    def __init__(self):
        super().__init__('llm_node')
        self.url = self.declare_parameter('ollama_url', 'http://10.8.0.1:11434').value
        self.model = self.declare_parameter('model', 'qwen3.8:27b').value
        self.pub = self.create_publisher(String, 'llm_reply', 10)
        self.create_subscription(String, 'user_text', self.on_text, 10)
        self.get_logger().info(f'Modèle {self.model} sur {self.url}')

    def on_text(self, msg):
        self.get_logger().info(f'Question : {msg.data}')
        try:
            r = requests.post(f'{self.url}/api/generate', timeout=120, json={
                'model': self.model, 'prompt': msg.data,
                'stream': False, 'think': False})
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
