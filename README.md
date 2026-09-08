# Wildfire Spread and Suppression Framework

셀 기반 산불 확산·진압 시뮬레이션 프로젝트입니다. 노트북에서 조건과 진압 전략을 실험하는 풀버전, 안드로이드 앱, 과학관 터치 전시물을 함께 관리합니다.

| 버전 | 위치 | 주요 기능 |
| --- | --- | --- |
| 노트북 풀버전 | [desktop](desktop) | 지도 선택, 기상 조건, 확산·진압 실험, 소방관을 포함한 진압 수단 |
| 안드로이드 앱 | [android_bulam_fire](android_bulam_fire) | Java 기반 모바일 확산·진압 체험 |
| 과학관 전시물 | [exhibit](exhibit) | 바람 비교 → 습도 비교 → 조작 안내 → 진압 게임 |

공통 지도는 `maps`, 전시 이미지와 한글 글꼴은 `assets`에 있습니다. 세 버전은 목적에 따라 조작 방식과 속도·진압 설정이 다르며, 같은 실행 설정을 공유하지 않습니다.

## 노트북 풀버전

Python 3.10 이상을 설치하고 저장소 루트에서 실행합니다. 가상환경 사용을 권장합니다.

```sh
python -m pip install -r desktop/requirements.txt
python desktop/v9.4_firespread_firefighter.py
```

v9.4는 소방관 기능을 포함한 풀버전입니다. 이전 v9.3도 `desktop/v9.3_firespread.py`로 보존했습니다. 지도 생성 도구는 `desktop/map_builder.py`이며 사용법은 파일 상단에 있습니다. 지도 선택 과정에서 생성되는 `active_map.json`과 피해 면적 로그는 버전 관리에서 제외됩니다.

## 안드로이드 앱

Android Studio에서 `android_bulam_fire` 폴더를 열고 SDK 36 및 프로젝트 Gradle 설정에 맞는 JDK를 구성합니다. Gradle 동기화 후 기기 또는 에뮬레이터에서 실행할 수 있습니다.

```sh
cd android_bulam_fire
./gradlew assembleDebug
```

Windows에서는 `gradlew.bat assembleDebug`를 사용합니다. APK는 `app/build/outputs/apk/debug/`에 생성됩니다. 배포 서명 키와 비밀번호는 포함하지 않았습니다. Release 서명은 본인 키로 별도 설정해야 합니다.

## 과학관 전시물

```sh
python -m pip install -r exhibit/requirements.txt
python exhibit/exhibit_v2.py
```

소스 실행은 노트북용 축소 창입니다. 1080×1920 세로 디스플레이를 기준으로 설계했으며 단일 터치·마우스로 조작합니다. EXE는 전체화면으로 실행됩니다.

- 바람·습도 비교: 불암산 지도와 비교용 고정 조건을 사용합니다.
- 게임: 캘리포니아 지도와 포함된 기상 CSV를 사용합니다.
- 진압 수단: 방화선, 비행기, 헬기, 소방차. 방화선은 드래그로 설치합니다.
- `게임으로 바로가기`도 조작 안내를 거칩니다. 종료는 Esc입니다.

### Windows EXE 만들기

저장소를 ZIP으로 내려받아 **모두 압축 해제**한 뒤 `exhibit/build_exhibit.bat`을 실행합니다. 최초 빌드에는 Python 3.10 이상과 인터넷이 필요합니다. 저장소 루트에 `wildfire_exhibit_v2.exe`가 생성되고 실행됩니다. 지도·이미지·글꼴은 EXE에 포함됩니다. 기존 EXE가 있으면 빌드 대신 실행하므로, 소스 변경 후에는 기존 EXE를 다른 곳으로 옮긴 뒤 다시 빌드하세요.

## 검증과 자료

안드로이드의 모델 상수·지도·참조 결과 검사는 아래 명령으로 실행합니다. 실제 기기의 실행 검증을 대신하지 않습니다.

```sh
python android_bulam_fire/verification/verify_android_fidelity.py
```

- [모델과 버전 구분](docs/MODEL.md)
- [자료 출처와 권리 안내](docs/ASSETS.md)

교육·연구용 모델이며 실제 재난 대응을 위한 예측·의사결정 시스템으로 검증된 제품은 아닙니다. 특정 산불에 대한 정량적 재현 정확도를 이 저장소만으로 주장하지 않습니다.
