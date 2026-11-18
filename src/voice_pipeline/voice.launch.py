from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
     return LaunchDescription([
          Node(package='voice_pipeline', executable='stt_node', output='screen'),
          Node(package='voice_pipeline', executable='llm_node', output='screen', parameters=[{'model': 'qwen3:8b'}]),
          Node(package='voice_pipeline', executable='tts_node', output='screen', parameters=[{'voice': 'af_heart'}]),
    ])