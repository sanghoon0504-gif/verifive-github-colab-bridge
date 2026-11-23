# VeriFive GitHub–Colab 연결 서버

GitHub Codespaces에서 실행되는 가벼운 reverse proxy입니다. 이용자는 Codespaces의 포트 주소로 접속하고, 실제 뉴스 수집·RAG·LLM 생성은 기존 Colab 서버에서 그대로 실행합니다.

```text
사용자 브라우저
      ↓ HTTPS
GitHub Codespaces :8000 (이 연결 서버)
      ↓ HTTPS + ngrok 안내 페이지 우회 헤더
Colab FastAPI :8000 (기존 UI/API)
      ↓
뉴스 수집 → RAG → LLM 생성
```

## 이 방식을 선택한 이유

- 최종 노트북의 UI와 API 코드를 바꾸지 않습니다.
- `/api/ask`, `/api/ask/status/{job_id}`, `/api/eval/batch`, `/api/eval/csv/{job_id}`처럼 기존 상대 경로 요청을 그대로 중계합니다.
- GitHub의 `GITHUB_TOKEN`, 인증 쿠키, Authorization 헤더는 Colab으로 전달하지 않습니다.
- 목표 Colab 주소는 환경 변수 하나로만 지정하므로 임의 주소로 요청을 별내는 open proxy가 아닙니다.
- GitHub Pages는 Python 서버를 실행할 수 없으므로 Pages 대신 Codespaces를 사용합니다.

## 전제

- 팀 GitHub 저장소와 Codespaces 사용 권한이 있어야 합니다.
- Colab에서 최종 UI 서버 셀과 ngrok 터널이 실행 중이어야 합니다.
- Codespaces가 GPU 모델을 대신 실행하는 것은 아닙니다. Colab이 종료되면 서비스도 멈춥니다.

## 실행 순서

### 1. 저장소 준비

이 폴드의 **내용물**을 팀 저장소 루트에 올립니다. 기존 팀 저장소가 있으면 새 저장소를 만들지 말고 그 저장소를 사용합니다.

포함된 설정:

- `.devcontainer/devcontainer.json`: Python 3.12, 의존성 설치, 8000 포트 전달
- `.github/workflows/test.yml`: push와 pull request 때 연결 서버 테스트
- `app.py`: Colab/ngrok 중계 코드
- `tests/test_bridge.py`: GPU 없이 실행하는 가짜 Colab 테스트

### 2. Codespaces 열기

GitHub 저장소에서 **Code → Codespaces → Create codespace**를 선택합니다. 첫 생성 때 `requirements-dev.txt`의 패키지가 설치됩니다.

### 3. Colab 주소 설정

Colab에서 최종 UI 서버 셀을 실행하고 출력된 ngrok 주소를 복사합니다. 끝의 `/`는 없어도 됩니다.

Codespaces 터미널에서:

```bash
export COLAB_BASE_URL='https://현재-주소.ngrok-free.dev'
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

ngrok 토큰, 네이버 API 키, GitHub 토큰은 이 저장소에 저장하지 않습니다.

### 4. 포트 확인

Codespaces의 **PORTS** 탭에서 `8000` 포트를 엽니다.

1. `/bridge/health`에서 `{"status":"ok","colab_configured":true}`가 보이는지 확인합니다.
2. 루트 주소에서 기존 VeriFive UI가 열리는지 확인합니다.
3. 테스트 질문을 한 번 제출하고 진행률, 완료, 결과 표시를 확인합니다.
4. 평가 기능을 쓴다면 상태 조회와 CSV 다운로드도 확인합니다.

처음에는 포트를 **Private**으로 두고 담당자가 확인합니다. 외부 시연에 꼭 필요한 경우에만 Port Visibility를 **Public**으로 바꿉니다. Public 포트는 URL을 아는 사람은 인증 없이 접속할 수 있으므로 시연 후 Private으로 되돌립니다.

### 5. ngrok 주소가 바뀐 경우

연결 서버를 `Ctrl+C`로 멈추고 새 주소를 설정한 뒤 다시 실행합니다.

```bash
export COLAB_BASE_URL='https://새-주소.ngrok-free.dev'
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Codespaces를 재시작하면 공개 포트 설정이 Private으로 돌아갈 수 있으므로 PORTS 탭을 다시 확인합니다.

## 로컬 검증

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

테스트는 실제 모델이나 외부 ngrok 서버를 호출하지 않습니다. 로컬 가짜 Colab 서버로 HTML, 질문 POST, 상태 조회, CSV, 민감 헤더 차단, 설정 누락을 확인합니다.

## 3-1 증빙 체크

실제 요구 플랫폼은 강사 확인이 남아 있습니다. Codespaces 실행이 인정된다면 다음 자료를 남깁니다.

- 저장소 주소와 검증한 커밋
- Codespaces의 8000 포트 실행 화면
- `/bridge/health` 정상 화면
- Codespaces URL로 접속한 VeriFive UI
- 질문 → 진행률 → 100% → 결과 화면
- API 상태 조회 또는 평가 CSV 다운로드 결과
- 테스트 일시와 담당자

## 현재 한계

- Colab과 ngrok에 의존하므로 상시 운영 서비스가 아닙니다.
- Codespaces 주소도 새 Codespace를 만들면 달라집니다.
- 요청 본문을 메모리에서 중계하므로 현재의 작은 JSON/CSV에는 적합하지만 대용량 파일 업로드용은 아닙니다.
- 실제 Codespaces와 현재 팀 ngrok 주소를 연결한 최종 시연은 별도로 확인해야 합니다. 로컬 테스트 통과만으로 배포 완료라고 표시하지 마세요.
