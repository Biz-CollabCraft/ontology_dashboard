# Decision record: policy B explicit current readiness and disclosed history

작성일: 2026-09-24  
근거: `docs/evidence/2026-09-24-current-readiness-supervised-cycle.md`

## Human-authorized implementation choice

The user authorized **policy B**: current readiness and disclosed historical availability must be separate API/type/ViewModel fields while preserving `EXACT_VALIDATED` and `LATEST_STORED` provenance.

Implemented contract:

- `current_ready=true` only for `EXACT_VALIDATED`.
- `historical_available=true` only for `LATEST_STORED`.
- no summary is `INELIGIBLE`, with both values false.
- HTTP 200 remains a transport/result-presence status; consumers must use the booleans rather than infer current readiness from it.

## Invariants retained

- exact key and scope binding remain unchanged;
- `LATEST_STORED` stays disclosed history and is not current-ready;
- generation-time context mismatch still blocks publication;
- GET does not acquire a provider-generation path;
- synthetic fixture results are not P0, provider, production, human-gold, or portfolio evidence.

## Human-owned completion fields

- **Final adoption / defer / reject:** pending human decision.
- **Interpretation of focused evidence:** pending human decision.
- **Changed belief:** pending human decision.
- **Decision Gate:** stop after reviewing the recorded 3-state synthetic verification and remaining limitations. No further implementation is authorized by this record.
