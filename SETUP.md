# SETUP — RTX 5070 Ti PC 개발 환경 구성 가이드

> 작성 2026-10-06 · 기획 v3.4 기준 · 대상: Isaac Sim이 설치될 **RTX 5070 Ti 데스크톱**
> 이 저장소를 `git clone`한 뒤 **이 문서부터** 따라 하세요. 끝나면 [`docs/weekly/W02`](docs/weekly/W02_2026-09-14_개발환경구축및아키텍처설계.md)의 완료 기준(DoD)을 확인할 수 있는 상태가 됩니다.

---

## 0. 지금 저장소에 있는 것 / 없는 것

| 있음 | 없음 (이 PC에서 새로 만든다) |
|---|---|
| 기획 · 설계 문서 `docs/` (범위 · 시나리오 40개 · 규칙/모드/이벤트 · 신호 → 액추에이터 지도) | Isaac Sim Scene (`worlds/`), 3D 자산 (`assets/`) |
| 설정 파일 `config/thresholds.yaml` (시스템 상수) · `config/user_modes.yaml` (사용자 모드) | ROS 2 노드 · 제어기 코드 (`scripts/`), 런치 파일 (`launch/`) |
| 주차 계획 `docs/weekly/W01–W15` | 시나리오 정의 `config/scenario_profiles.yaml`, 실험 결과 (`results/`) |

목표 폴더 구조는 [`README.md` §10](README.md)에 있습니다.

---

## 1. 권장 구성 (2026-10 기준)

| 항목 | 권장 | 비고 |
|---|---|---|
| OS | **Ubuntu 24.04 LTS** | Windows 11도 지원되지만 ROS 2 연동이 번거롭다(§9). 듀얼 부팅 권장 |
| GPU | GeForce RTX 5070 Ti (Blackwell · 16 GB) | 아래 참고 |
| NVIDIA 드라이버 | **595.58.03 이상** (Linux) / 595.97 이상 (Windows) | Isaac Sim 6.x 요구 버전. RTX 50 시리즈는 구버전 드라이버에서 인식 안 됨 |
| Isaac Sim | **6.1.0** (작성 시점 최신 · pip 설치) | 설치 직전 [릴리스 노트](https://docs.isaacsim.omniverse.nvidia.com/latest/overview/release_notes.html)로 최신 안정판 확인 |
| Python | **3.12** | Isaac Sim 6.x 런타임 · Ubuntu 24.04 · ROS 2 Jazzy가 모두 3.12 → 한 버전으로 통일 |
| ROS 2 | **Jazzy** | Ubuntu 24.04 권장 조합 · 통신은 기본 Fast DDS |
| RAM / 저장공간 | 32 GB 이상 / SSD 50 GB 이상 (권장 500 GB) | Isaac Sim 캐시 · 셰이더 캐시가 크다 |

> **RTX 5070 Ti와 공식 사양:** Isaac Sim 6.x 문서의 최소 GPU는 RTX 4080(16 GB)입니다. 5070 Ti는 VRAM은 같고 성능은 비슷하거나 조금 낮습니다.
> 원룸 Scene 하나는 충분하지만, 렌더 해상도와 레이 트레이싱 품질은 낮춰 두는 편이 안전합니다.
> 이 프로젝트의 시나리오 대부분(32개)은 **Isaac Sim 없이 도는 고속 모드**라 GPU 영향을 거의 받지 않습니다([`docs/03` §5.3](docs/03_scenarios.md)).

**버전은 설치 후 §10 기록표에 실제 값을 적고 팀원 모두 같은 조합을 씁니다.**

---

## 2. 사전 확인

```bash
nvidia-smi                       # 드라이버 버전 · GPU 인식 · CUDA 버전
ldd --version | head -1          # GLIBC 2.35 이상 (pip 설치 조건)
python3.12 --version             # Ubuntu 24.04 기본 탑재
df -h ~                          # 여유 공간 50 GB 이상
```

드라이버가 낮으면 Ubuntu "추가 드라이버" 또는 `sudo ubuntu-drivers install`로 595 이상 production 브랜치를 설치하고 재부팅합니다.

---

## 3. 저장소 받기

```bash
mkdir -p ~/workspace && cd ~/workspace
git clone <GitHub 저장소 URL> actuator_workspace
cd actuator_workspace
git config core.quotepath false   # 한글 파일명(docs/weekly)이 깨져 보이지 않게
```

---

## 4-A. ✅ 현행 — Isaac Sim 5.1 Docker 전용 컨테이너 (2026-10-09 결정 · 방법 A)

이 PC에는 다른 프로젝트용 이미지 `teleop-docker`(Isaac Sim 5.1 · Isaac Lab)가 이미 있다. **이미지는 공유하되 컨테이너 · 캐시는 이 프로젝트 전용**으로 쓴다.
로컬 설치 · 드라이버 업그레이드 없이 쓸 수 있고, 다른 프로젝트 환경을 건드리지 않는다.

```bash
tools/isaac/run.sh python tools/isaac/check_effort_sensor.py   # 헤드리스 스크립트 (Effort Sensor 검증)
tools/isaac/run.sh gui                                         # GUI (X11)
tools/isaac/run.sh shell                                       # 컨테이너 셸
```

- 이미지 entrypoint(다른 프로젝트 패키지 설치)를 우회하고 `/isaac-sim/python.sh` 를 직접 쓴다
- 캐시 · 로그: `~/docker/studio-isaac/` · 저장소는 컨테이너의 `/workspace/studio` 에 마운트
- **Isaac Sim 쪽 Python은 3.11**(이미지 내장)이다. 시뮬레이터 스크립트(`tools/isaac/`, 이후 Scene · 브릿지)는 3.11에서 돌고,
  제어기 · 환경 모델 · 하네스는 호스트 uv `.venv`(3.12)에서 돈다 — 둘 사이는 ROS 2 토픽으로만 연결한다
- 아래 §4(pip 6.1 설치)는 **대안**으로 남겨 둔다 (드라이버 595+ 필요)

## 4. (대안) Isaac Sim 6.1 설치 (pip · 가상환경)

```bash
cd ~/workspace
python3.12 -m venv env_isaacsim
source env_isaacsim/bin/activate
pip install --upgrade pip

pip install "isaacsim[all,extscache]==6.1.0.0" --extra-index-url https://pypi.nvidia.com

export OMNI_KIT_ACCEPT_EULA=YES                 # 첫 실행 전 EULA 동의 (~/.bashrc 에 추가 권장)
isaacsim isaacsim.exp.compatibility_check       # 호환성 검사 앱 — GPU · 드라이버 판정 확인
isaacsim                                        # 첫 실행은 셰이더 컴파일로 수 분 걸린다
```

- 대안: [워크스테이션 설치(zip)](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_workstation.html) → `./isaac-sim.sh` 실행, `./python.sh 스크립트.py`로 내장 Python 사용
- `env_isaacsim/`은 저장소 **밖**(`~/workspace/`)에 둡니다 — `.gitignore`에도 등록되어 있지만, 저장소 안에 두면 검색 · 동기화가 느려집니다

---

## 5. ROS 2 Jazzy 설치 + Isaac Sim 브릿지

> **이 PC의 결정 (2026-10-10): 호스트에 ROS 2 를 설치하지 않는다 — 공식 `ros:jazzy` Docker 컨테이너에서 돌린다.**
> 같은 PC에서 다른 프로젝트(manipulator_ws)가 호스트 환경을 쓰고 있어 건드리지 않기 위함이다.
> - 이미지: `ros:jazzy-ros-base` (필요 시 `ros-jazzy-rmw-fastrtps-cpp` 추가) · 컨테이너는 `--network host --ipc host` 로 띄워
>   Isaac Sim 컨테이너(§4-A)와 같은 호스트 네트워크에서 DDS 가 서로 보이게 한다
> - 두 컨테이너 모두 `ROS_DOMAIN_ID=7` · `RMW_IMPLEMENTATION=rmw_fastrtps_cpp` 로 맞춘다
> - 저장소는 컨테이너에 `-v $PWD:/ws` 로 마운트 — 제어기 · 하네스 코드는 그대로 쓰고 rclpy 래퍼 노드만 컨테이너에서 실행한다
> - 실행 스크립트는 W08–W09 ROS 브릿지 작업(10/19–22)에서 `tools/ros/run.sh` 로 만든다
> 아래 deb 설치 절차는 호스트 설치를 택하는 다른 PC용으로 남겨 둔다.

공식 절차: [ROS 2 Jazzy — Ubuntu (deb)](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)

```bash
# 공식 절차대로 저장소 등록 후
sudo apt install ros-jazzy-desktop ros-dev-tools
sudo apt install ros-jazzy-vision-msgs ros-jazzy-ackermann-msgs   # Isaac Sim 예제가 쓰는 메시지

echo 'source /opt/ros/jazzy/setup.bash' >> ~/.bashrc
echo 'export ROS_DOMAIN_ID=7' >> ~/.bashrc                 # 팀 내 다른 PC와 충돌 방지 (임의 값)
echo 'export RMW_IMPLEMENTATION=rmw_fastrtps_cpp' >> ~/.bashrc
```

**Isaac Sim 쪽:** `Window → Extensions`에서 **`isaacsim.ros2.bridge`** 활성화 (기본 활성).
Ubuntu 24.04에서는 ROS를 source하지 않아도 Isaac Sim이 **내장 Jazzy 라이브러리**를 자동으로 씁니다.
시스템 ROS 2를 source한 터미널에서 Isaac Sim을 실행해도 됩니다 — Python 3.12로 버전이 같기 때문입니다.

**확인**
```bash
# 터미널 1: Isaac Sim 실행 → 빈 Stage에서 Play
# 터미널 2:
ros2 topic list          # /clock 등 Isaac Sim 토픽이 보이면 성공
```

---

## 6. 프로젝트 Python 패키지 (고속 모드 · 분석) — uv

고속 모드 하네스 · 환경 모델 · 제어기 단위 테스트는 **저장소 안의 uv 가상환경(`.venv`)** 에서 돌린다.
시스템 Python · conda · 다른 프로젝트 환경은 건드리지 않는다. 인터프리터는 **시스템 `/usr/bin/python3.12`**(ROS 2 Jazzy와 같은 버전)를 쓴다.

```bash
cd ~/studio-smart-home-sim
UV_PYTHON_DOWNLOADS=never uv sync --python /usr/bin/python3.12   # pyproject.toml · uv.lock 기준으로 .venv 생성
uv run pytest                                                     # 단위 테스트
uv run python -c "import yaml; yaml.safe_load(open('config/thresholds.yaml')); print('config ok')"
```

- 의존성은 `pyproject.toml`에서 관리한다(`uv add <패키지>`). `requirements.txt`는 참고용으로 남겨 둔다
- ROS 2 노드(rclpy)는 ROS 2 설치 후 별도로 다룬다 — 제어 로직(`scripts/controller/`) · 환경 모델(`scripts/env_model/`)은 ROS 없이 돈다

## 7. 첫날 검증 체크리스트 (W02 리스크 항목)

| # | 확인 | 방법 | 실패 시 |
|---|---|---|---|
| 1 | 드라이버 · GPU | `nvidia-smi` · 호환성 검사 앱 | 드라이버 595+ 재설치 |
| 2 | Isaac Sim 실행 | 빈 Stage → Play, 큐브 낙하 | 셰이더 캐시 삭제 후 재실행 · 로그(`~/.nvidia-omniverse/logs`) 확인 |
| 3 | ROS 2 브릿지 | `ros2 topic list`에 `/clock` | `isaacsim.ros2.bridge` 활성화 · `ROS_DOMAIN_ID` 일치 확인 |
| 4 | ⚠️ **Effort Sensor API** | 아래 스크립트 | **센서리스 창문 제어의 전제** — 대체 API로 검증 ([`docs/04`](docs/04_sensorless_window_control.md)) |
| 5 | 브릿지 PoC | 토픽으로 큐브 하나 움직이기 (`scripts/poc_bridge.py`) | 실패 원인 기록 → 파일 · 소켓 IPC 대체안 |

**4번 — Effort Sensor 확인** (Isaac Sim `Window → Script Editor`에서 실행)
```python
import omni.kit.app
mgr = omni.kit.app.get_app().get_extension_manager()
print(sorted(e["id"] for e in mgr.get_extensions() if "sensor" in e["id"]))
# 기대: isaacsim.sensors.experimental.physics (또는 이름이 바뀐 physics 센서 확장)
```
- 확장 이름이 바뀌었으면 **실제 경로를 §10 기록표와 [`docs/04`](docs/04_sensorless_window_control.md)에 적습니다**
- 대체안: Articulation의 `get_measured_joint_efforts()` (DOF 힘 센서 활성화 필요)
- 최소 검증: Prismatic 조인트를 벽에 밀었을 때 힘 값이 올라가는지

---

## 8. 작업 시작 — 폴더 만들기와 순서

```bash
cd ~/workspace/actuator_workspace
mkdir -p worlds assets scripts/controller launch results
```

| 순서 | 내용 | 근거 문서 |
|---|---|---|
| ① | 환경 구성 · 검증 (이 문서) | W02 |
| ② | 원룸 Scene (3.5 × 5 m) · 창문 랙-피니언 · 문 · 존 | W03 · [`docs/02`](docs/02_scope_definition.md) |
| ③ | 액추에이터 모듈 · 조인트 구동 · 센서 측정점 | W04 · W05 |
| ④ | **고속 모드 환경 모델 + 하네스를 먼저** — 시나리오 대부분이 여기서 돈다 (일정 최대 리스크) | W08 · W10 · [`docs/00`](docs/00_project_schedule.md) 리스크 1 |
| ⑤ | 가상 센서 노드 → 제어기(모드 · 규칙 · 이벤트 · 중재) | W06–W09 · [`docs/07`](docs/07_modes_rules_events.md) |

> 일정상 오늘(2026-10-06)은 W05입니다. 환경 구성이 끝나면 [`docs/00_project_schedule.md`](docs/00_project_schedule.md)의 W02–W05 항목을 함께 따라잡습니다.

**처음 읽을 문서:** [`README.md`](README.md) → [`docs/09_signal_actuator_map.md`](docs/09_signal_actuator_map.md) (한 장 요약) → [`docs/02`](docs/02_scope_definition.md) (토픽 55개 · 가정) → [`docs/07`](docs/07_modes_rules_events.md) (규칙 · 이벤트) → [`docs/03`](docs/03_scenarios.md) (시나리오 · 판정 기준)

---

## 9. Windows 11에서 할 경우 (대안)

- Isaac Sim 6.x는 Windows 11을 지원합니다(Windows 10 미지원). 드라이버 595.97 이상
- ROS 2는 **Pixi 기반 Jazzy**가 공식 권장 경로입니다 — [Isaac Sim ROS 2 설치 문서](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_ros.html)의 Windows 절
- WSL2 + Humble 방식은 공식 문서에서 **사용 중단 예정(deprecated)** 으로 표시되어 있어 권장하지 않습니다
- 셸 예시는 `export` 대신 `set` (`set OMNI_KIT_ACCEPT_EULA=YES`)

---

## 10. 버전 기록표 — 설치 후 실제 값으로 채운다

| 항목 | 값 | 확인일 · 담당 |
|---|---|---|
| OS / 커널 | Ubuntu 24.04.5 LTS / 7.0.0-31-generic | 2026-10-09 |
| NVIDIA 드라이버 / CUDA | 580.178.04 / CUDA 13.0 (GPU RTX 5070 Ti 16 GB 인식) — 문서 권장 595+ 미만 | 2026-10-09 |
| Isaac Sim | **5.1.0-rc.19 — Docker 이미지 `teleop-docker` 안 `/isaac-sim`, 전용 컨테이너 `tools/isaac/run.sh`(§4-A)** · 내장 Python 3.11.13 · 헤드리스 실행 확인 | 2026-10-09 |
| Python (Isaac Sim / 시스템) | 3.11.13 (Docker 내장) / **3.12.3** (`/usr/bin/python3.12`, uv `.venv`) | 2026-10-09 |
| ROS 2 배포판 · RMW | **Jazzy — 공식 `ros:jazzy` Docker 컨테이너(§5, 호스트 미설치 유지)** · Fast DDS · `ROS_DOMAIN_ID=7` · Isaac Sim 브릿지 내장 `jazzy` 라이브러리 존재 | 2026-10-10 |
| Effort Sensor 확장 경로 | `isaacsim.sensors.physics.EffortSensor` (prim_path = 루트/조인트명) · 대체 `get_measured_joint_efforts()` — **✅ 실증 PASS** (0 N → 300 N) | 2026-10-09 |
| 호환성 검사 결과 | 미실시 | |

## 11. 자주 막히는 곳

| 증상 | 원인 · 해결 |
|---|---|
| Isaac Sim 시작 직후 CUDA · RTX 초기화 오류 | 드라이버가 Blackwell을 지원하지 않는 버전 → 595+ 설치 |
| `ros2 topic list`에 아무것도 안 보임 | 브릿지 확장 비활성 · `ROS_DOMAIN_ID` 불일치 · 방화벽(DDS 포트) |
| 브릿지가 라이브러리를 못 찾음 | 내장 라이브러리 사용 시 `LD_LIBRARY_PATH`에 `<isaac_sim 경로>/exts/isaacsim.ros2.core/jazzy/lib` 추가 |
| 한글 파일명이 `\354\236...`로 보임 | `git config core.quotepath false` |
| `config/*.yaml` 수정 후 ROS 2 파라미터 로드 실패 | 키가 숫자로 시작하거나 `null` 값이 있음 — `thresholds.yaml`은 ROS 2 규칙(숫자 키 금지 · null 대신 -1.0)을 지킨다 |

---

**참고 (설치 문서):**
[Isaac Sim 요구 사양](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html) ·
[Isaac Sim pip 설치](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_python.html) ·
[Isaac Sim ROS 2 설치](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_ros.html) ·
[ROS 2 Jazzy 설치](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)
