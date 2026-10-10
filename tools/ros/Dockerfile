# 이 프로젝트 전용 ROS 2 Jazzy 이미지 (SETUP §5) — 공식 ros:jazzy-ros-base 에 제어기 의존성만 더한다
# 호스트에는 ROS 를 설치하지 않는다. 빌드: tools/ros/run.sh build
FROM ros:jazzy-ros-base
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-numpy python3-yaml ros-jazzy-rmw-fastrtps-cpp \
    && rm -rf /var/lib/apt/lists/*
ENV RMW_IMPLEMENTATION=rmw_fastrtps_cpp
WORKDIR /workspace/studio
