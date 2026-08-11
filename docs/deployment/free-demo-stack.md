# Free demo deployment baseline

Week 2/MVP 공유 환경은 다음 세 서비스를 사용한다.

```text
GitHub
  ├─ Vercel: systems/frontend (PR Preview + main Production)
  └─ Render: systems/backend (main, CI checks pass 후 자동 배포)
        └─ Neon PostgreSQL
```

## Vercel

- Git repository: `Biz-CollabCraft/ontology_dashboard`
- Root Directory: `systems/frontend`
- Framework: Vite
- Build: `npm run build`
- Output: `dist`
- Production branch: `main`
- Environment variable: `VITE_API_BASE_URL=<Render public URL>`

`systems/frontend/vercel.json`은 SPA deep-link fallback을 보장한다.

## Render

루트 `render.yaml`을 Blueprint로 사용한다. Backend는
`systems/backend/Dockerfile`을 그대로 빌드하며 `/health/live`를 health check로 사용한다.

비밀값은 저장소에 커밋하지 않는다. Render Dashboard에서 다음 Secret Env Var를 직접
입력한다.

```text
ONTOLOGY_DASHBOARD_DATABASE_URL=<Neon direct PostgreSQL connection string>
```

무료 demo 환경은 `APP_ENV=demo`를 사용한다. 이는 Week 2 fixture 및 explicit heuristic
fallback을 허용하기 위한 설정이며 production security profile을 의미하지 않는다.

## Neon

Neon의 direct PostgreSQL connection string을 Render Secret Env Var로만 전달한다.
Migration/bootstrap은 Backend 시작 시 idempotent하게 실행된다.

## CORS

Vercel Preview URL은 매 PR마다 달라지므로 Backend는
`ONTOLOGY_DASHBOARD_ALLOWED_ORIGIN_REGEX`를 지원한다. Demo Blueprint는
`^https://.*\\.vercel\\.app$`만 허용한다.

Production으로 승격할 때는 고정 HTTPS origin을 `ONTOLOGY_DASHBOARD_ALLOWED_ORIGINS`에
추가하고 preview regex 범위를 재검토한다.
