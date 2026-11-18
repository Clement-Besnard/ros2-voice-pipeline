from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
     return LaunchDescription([
          Node(package='voice_pipeline', executable='stt_node', output='screen'),
          # Le modèle n'est plus réglé ici : il vient de N8N_OLLAMA_MODEL (.env).
          Node(package='voice_pipeline', executable='llm_node', output='screen', parameters=[{'session_id': 'ros-voice'}]),
          Node(package='voice_pipeline', executable='tts_node', output='screen', parameters=[{'voice': 'af_heart'}]),
    ])