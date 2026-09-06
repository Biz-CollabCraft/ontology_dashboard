# 근거 확인 영역의 AI 브리핑 연결

구현: 캡처의 상단 설명에 저장된 검증 통과 LLM summary를 표시한다. 기존 네 항목과 여섯 칸 숫자는 구조화된 서버 근거를 유지한다. AI 조회/생성 중, 생성 전, 실패/fallback을 구분한다. 기존 agent-review-summary GET/POST를 재사용하며 권한·CSRF를 우회하지 않는다. GET은 생성하지 않는다. 생성 후 GET으로 재조회한다. generation/abort 보호로 다른 설비 응답이 섞이지 않게 한다.

범위: manufacturing-demo workspace에만 기존 summary 계약이 있다. 다른 workspace는 계약 미지원 표시. 생성 권한은 기존 agent.review.materialize를 따른다. 엔지니어는 저장 결과 조회 가능, 생산관리자는 생성 가능. 역할 탭 변경은 권한에 영향 없음.

AI Packet의 최근 30일 사건 수를 동일 snapshot의 factory-records 서버 조회로 보완하고 출처·정책을 넣었다. 캐시 context hash가 달라지므로 이전 누락 근거 요약을 재사용하지 않는다.

검증: 프론트 표시 검사 13개, 빌드 통과. 실제 PostgreSQL의 summary GET은 엔지니어·관리자 모두 202(summary_not_materialized), 생성 버튼은 관리자만 활성화. connection.json, connected-pending.png 참조.

실제 생성 검증 완료: 사용자 명시 승인 후 기존 OpenAI gpt-4o-mini 설정으로 선택한 CMP-S03-L03-01 한 건을 생성했다. POST 200, mode=llm, fallback=false, validation_errors=[], materialization.status=ready. PostgreSQL 저장 후 GET과 페이지 새로고침에서 동일 summary_id `279db77b-5618-4328-9714-e06cd9470a77` 및 summary_key를 확인했다. generation-result.json과 generated.png 참조. 현재 서버는 실제 provider 설정의 /tmp/start-standalone-api.py로 실행 중이다.

생성 내용은 기존 예측 위험도와 근거 한계를 설명한다. 부하 등급·최근 7일 가동시간·생산 영향 등급은 여전히 입력 근거가 없으며 이 생성으로 보충된 값이 아니다.

이 연결은 저장된 Product Result의 읽기 전용 브리핑이며 새 예측 모델 추론·정비 자동 실행을 추가한 것은 아니다. fallback을 실제 AI 결과로 표시하지 않는다.
