"""물리 모드 런치 초안 (W06 T6.4) — ROS 컨테이너 쪽 노드들.

    (Isaac 컨테이너)  tools/isaac/run.sh python scripts/sim/isaac_actuator_bridge.py
    (ROS 컨테이너)    tools/ros/run.sh ros2 launch launch/studio_smart_home.launch.py [stub:=true]

Isaac 브릿지는 Isaac 내장 Python 이 돌려야 해서 이 런치에 넣지 않는다 (컨테이너가 다르다).
센서 노드(W07)가 생기면 여기에 더한다 — 그 전까지는 stub:=true 로 센서 스텁을 띄운다.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    stub = LaunchConfiguration("stub")
    return LaunchDescription([
        DeclareLaunchArgument("stub", default_value="false", description="W07 전 시험용 센서 스텁"),
        DeclareLaunchArgument("baseline", default_value="proposed"),
        ExecuteProcess(cmd=["python3", "scripts/nodes/smart_home_node.py", "--baseline",
                            LaunchConfiguration("baseline")], output="screen"),
        ExecuteProcess(cmd=["python3", "scripts/nodes/appliance_bridge_node.py"], output="screen"),
        ExecuteProcess(cmd=["python3", "scripts/nodes/sensor_stub_node.py", "--mode", "STUDY", "--temp", "29"],
                       output="screen", condition=IfCondition(stub)),
    ])
