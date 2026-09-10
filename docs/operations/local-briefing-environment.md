# 로컬 브리핑 서버 환경 설정

2026-09-09 실제 화면 검증 중 `.env`에 모델과 API 키가 있었지만 직접 실행한 uvicorn이 파일을 읽지 않아 ProviderUnavailable이 발생했다. 계정 권한이나 점검 완료 상태가 원인이 아니었다.

## 실행 전 확인

1. 실행할 worktree와 `.env` 절대 경로를 확인한다. 다른 checkout의 설정을 자동으로 읽는다고 가정하지 않는다.
2. `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` 또는 `OPENAI_API_KEY`를 확인한다. 키는 존재 여부만 출력한다.
3. 현재 OpenAI 호환 provider는 `LLM_API_KEY`를 우선하고 없으면 `OPENAI_API_KEY`를 사용한다. 모델 또는 키가 빈 값이면 생성 전에 실패한다.
4. uvicorn의 `--env-file`은 이미 설정된 프로세스 환경변수를 덮어쓰지 않는다. 특히 테스트에서 빈 값으로 export한 LLM 변수는 해제하거나 의도한 값으로 설정한다.
5. `.env`가 가리키는 DB를 그대로 사용하지 않도록 `DATABASE_URL`, `ONTOLOGY_DASHBOARD_DB`, `APP_ENV`를 명시한다.

## 직접 실행

저장소 루트에서 사용한다. `BACKEND_PYTHON`은 python-dotenv와 uvicorn이 설치된 가상환경 Python 경로다. worktree에 가상환경이 없으면 기존 checkout의 가상환경을 명시한다. `GEN_DATA_OUTPUT_ROOT`는 화면이 읽을 기존 gen_data 출력 폴더다.

```bash
APP_ENV=test DATABASE_URL='' \
ONTOLOGY_DASHBOARD_DB=/private/tmp/ontology-evidence-ui.sqlite \
SEED_DEMO_ACCOUNTS=1 \
ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1 \
PYTHONPATH=systems/backend:ml/src:tests:. \
"${BACKEND_PYTHON}" -m uvicorn app.main:app \
  --env-file "$PWD/.env" --host 127.0.0.1 --port 8317
```

`GEN_DATA_OUTPUT_ROOT`도 실행 환경에 설정해야 한다. 프론트는 `VITE_API_PROXY_TARGET=http://127.0.0.1:8317`로 같은 백엔드를 바라보게 한다. `scripts/run_local.sh`는 자체적으로 `.env`를 source하므로 직접 uvicorn 실행과 구분한다.

## 실행 후 확인

- health와 로그인 확인 후, 승인된 가정 데이터로 브리핑 생성 요청을 실행한다.
- 저장 trace의 provider, model, fallback reason을 확인한다. `LLM credentials or model are not configured`는 설정 전달 실패이고, 응답 내용 검증 실패와 다르다.
- 생성 성공 후 같은 사건을 재조회하여 저장된 브리핑이 유지되는지 확인한다. HTTP 200 또는 생성 버튼 표시만으로 성공 처리하지 않는다.
- 기존 실패 캐시가 보이면 설정 반영 후 명시적 생성을 요청한다. 새 서버로 재시작해도 브라우저에 있던 오류 문구는 자동으로 사라지지 않을 수 있다.
- 픽스처 테스트 통과와 실제 LLM 생성 성공을 별도로 기록한다.

## 이번 재검증 결과

사용자 승인 후 기존 `.env`의 LLM 설정을 실행 프로세스에 전달하고 재시작했다. CMP-S01-L04-01 생성 결과는 `status=ready`, `model_version=openai-compatible:gpt-4o-mini`, `fallback=false`로 저장됐다. 브라우저 새로고침 후 항목을 다시 선택해 저장본이 표시되는 것도 확인했다.

연결 성공과 내용 정확성은 별개다. 현재 FILE 사건 패킷에는 저장된 점검 이력이 빠져 있어 생성문이 실제 완료된 점검을 기록 없음으로 설명했다. 이 이력 연결 문제는 이번 환경 수정으로 해결된 것이 아니다.
