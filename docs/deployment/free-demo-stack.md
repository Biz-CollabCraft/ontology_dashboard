# Mac mini demo deployment baseline

공유 환경의 정본은 Vercel Preview가 아니라 Mac mini의
`https://ontology.oosu.dev/`이다.

```text
pull_request
  └─ GitHub-hosted Actions: unit / build / Playwright / architecture

main push
  └─ architecture workflow green
       └─ Mac mini outbound release watcher
            └─ verified main SHA pull
                 └─ Frontend container :8120
                      └─ Cloudflare Tunnel → ontology.oosu.dev
```

## CI and CD ownership

- PR은 GitHub-hosted runner에서 검증하고 외부 Preview deployment를 만들지 않는다.
- `architecture` workflow가 `main` push에 대해 성공한 SHA만 Mac mini CD가 소비한다.
- 저장소가 public이므로 Mac mini를 repository self-hosted runner로 노출하지 않는다.
- Mac mini의 launchd watcher가 outbound로 `main` 및 GitHub Actions 상태를 확인하고 검증된 SHA만 pull한다.
- Frontend 입력(`systems/frontend`, `docs`)이 마지막 평가 SHA 이후 바뀌지 않았다면 배포를 건너뛴다.
- 배포 실패 시 직전 Frontend image로 rollback하고 workflow를 실패 처리한다.

## Mac mini runtime

- Public URL: `https://ontology.oosu.dev/`
- Frontend origin: `127.0.0.1:8120`
- Backend origin: `127.0.0.1:8110`
- Frontend container는 기존 `ontology-dashboard-macmini_private` network에 연결되어
  same-origin `/api/*` 요청을 `api:8000`으로 proxy한다.
- Cloudflare Tunnel과 Backend/PostgreSQL/Redis/live ingestion runtime은 Frontend CD가
  재생성하거나 중단하지 않는다.

## Secrets

Frontend CD는 GitHub secret을 Mac mini로 전송하지 않는다. Release watcher는 public Git/GitHub
API를 읽기만 하고 Mac mini에서 이미 실행 중인 Docker/OrbStack과 production network만 사용한다.
Backend/database/model secrets는 기존 Mac mini production runtime의 로컬 secret/environment
관리 범위에 남긴다.
