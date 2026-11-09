# ROS

 Robotic Operating System

## Commands

```
ros2 run voice_pipeline echo_node
```

```
ros2 run voice_pipeline llm_node
```

```
ros2 topic echo /llm_reply
```

```
ros2 topic pub --once /user_text std_msgs/msg/String "data: 'whats the weather in paris today ?'"
```