# ask.py — tape tes questions, Entrée pour envoyer, Ctrl+C pour quitter
import threading, time, rclpy
from rclpy.node import Node
from std_msgs.msg import String

def main():
    rclpy.init()
    n = Node('ask')
    pub = n.create_publisher(String, 'user_text', 10)
    t0 = [0.0]

    def on_reply(m):
        print(f'\n< {m.data}  ({time.perf_counter() - t0[0]:.2f}s)\n> ', end='', flush=True)

    n.create_subscription(String, 'llm_reply', on_reply, 10)
    threading.Thread(target=rclpy.spin, args=(n,), daemon=True).start()
    try:
        while True:
            q = input('> ').strip()
            if q:
                t0[0] = time.perf_counter()
                pub.publish(String(data=q))
    except (KeyboardInterrupt, EOFError):
        pass
    rclpy.shutdown()

if __name__ == '__main__':
    main()