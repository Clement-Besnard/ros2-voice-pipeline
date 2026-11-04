import rclpy
from rclpy.node import Node
from std_msgs.msg import String

class EchoNode(Node):
    def __init__(self):
        super().__init__('echo_node')
        self.pub = self.create_publisher(String, 'llm_reply', 10)
        self.create_subscription(String, 'user_text', self.cb, 10)

    def cb(self, msg):
        self.get_logger().info(f'Reçu : {msg.data}')
        self.pub.publish(String(data=msg.data.upper()))

def main():
    rclpy.init()
    rclpy.spin(EchoNode())
    rclpy.shutdown()