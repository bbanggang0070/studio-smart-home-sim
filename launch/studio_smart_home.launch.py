"""물리 모드 런치 (W06 T6.4 · W07) — ROS 컨테이너 쪽 노드 전부.

    (Isaac 컨테이너)  tools/isaac/run.sh python scripts/sim/isaac_actuator_bridge.py
    (ROS 컨테이너)    tools/ros/run.sh ros2 launch launch/studio_smart_home.launch.py scenario:=B12

    Isaac 없이 시험:  ... scenario:=B12 fast_actuators:=true speed:=5
      월드 노드의 1차 지연 액추에이터가 상태 토픽을 대신 내고, 재실 노드는 문 접점을 참값에서 읽는다.

Isaac 브릿지는 Isaac 내장 Python 이 돌려야 해서 이 런치에 넣지 않는다 (컨테이너가 다르다).
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression


def _node(script, *args, **kw):
    return ExecuteProcess(cmd=["python3", f"scripts/nodes/{script}", *args], output="screen", **kw)


def generate_launch_description():
    scenario = LaunchConfiguration("scenario")
    fast = LaunchConfiguration("fast_actuators")
    speed = LaunchConfiguration("speed")
    stub = LaunchConfiguration("stub")
    world_on = PythonExpression(["'", stub, "' != 'true'"])
    return LaunchDescription([
        DeclareLaunchArgument("scenario", default_value="B12", description="config/scenario_profiles.yaml 의 id"),
        DeclareLaunchArgument("fast_actuators", default_value="false", description="Isaac 없이 시험"),
        DeclareLaunchArgument("speed", default_value="1.0", description="시뮬레이션 배속 (Isaac 과 함께면 1)"),
        DeclareLaunchArgument("baseline", default_value="proposed"),
        DeclareLaunchArgument("rep", default_value="1", description="반복 번호 (로그 파일 이름)"),
        DeclareLaunchArgument("stub", default_value="false", description="W06 시험용 고정 센서 스텁 (월드 · 센서 노드 대신)"),
        _node("smart_home_node.py", "--baseline", LaunchConfiguration("baseline"), "--scenario", scenario),
        _node("appliance_bridge_node.py"),
        # 시나리오 월드 + 센서 노드 (W07)
        ExecuteProcess(cmd=["python3", "scripts/nodes/scenario_world_node.py", "--scenario", scenario, "--speed", speed,
                            "--fast-actuators"], output="screen",
                       condition=IfCondition(PythonExpression(["'", fast, "' == 'true' and ", world_on]))),
        ExecuteProcess(cmd=["python3", "scripts/nodes/scenario_world_node.py", "--scenario", scenario, "--speed", speed],
                       output="screen",
                       condition=IfCondition(PythonExpression(["'", fast, "' != 'true' and ", world_on]))),
        _node("environment_sensor_node.py", condition=IfCondition(world_on)),
        _node("experiment_logger_node.py", "--scenario", scenario, "--baseline", LaunchConfiguration("baseline"),
              "--rep", LaunchConfiguration("rep"), condition=IfCondition(world_on)),
        _node("power_monitor_node.py", condition=IfCondition(world_on)),
        _node("occupancy_sensor_node.py", "--door-from-truth",
              condition=IfCondition(PythonExpression(["'", fast, "' == 'true' and ", world_on]))),
        _node("occupancy_sensor_node.py",
              condition=IfCondition(PythonExpression(["'", fast, "' != 'true' and ", world_on]))),
        _node("sensor_stub_node.py", "--mode", "STUDY", "--temp", "29", condition=IfCondition(stub)),
    ])
