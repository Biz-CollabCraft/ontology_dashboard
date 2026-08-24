# Generator Feature Input Golden Vector v1

본 디렉터리는 Generator Feature 파이프라인의 Multi-asset 및 Lookahead horizon 라벨링 / 활성 고장 제외 계약을 검증하는 Golden Test Vector입니다.

## 시나리오 명세

- **Observation Dataset**: `asset-A`, `asset-B` (각 6개 타임스탬프, 총 12개 행)
- **Failure Dataset**: `asset-A` 2026-08-24 03:00:00 고장 (exclusion_end: 2026-08-24 04:00:00)
- **Prediction Horizon**: 2시간 (`[01:00, 03:00)`)
- **기대 동작**:
  1. `asset-A`: 01:00, 02:00 -> 라벨 1 (2행); 03:00, 04:00 -> 활성 고장 구간 제외 (2행); 00:00, 05:00 -> 라벨 0 (2행). 생존 4행.
  2. `asset-B`: 고장 이벤트 영향 없음 -> 6행 모두 생존, 모두 라벨 0.
  3. 총 생존 10행, 양성 2개, 음성 8개.
