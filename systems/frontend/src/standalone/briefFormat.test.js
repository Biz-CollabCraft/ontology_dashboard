import {it,expect} from 'vitest';
import {briefRows,relativeRecordTime,readableUnits,referenceLabels,readerLimitations} from './briefFormat.js';
it('uses Korean calendar days across midnight and older records',()=>{
 const now='2026-09-08T00:01:00+09:00';
 expect(relativeRecordTime('2026-09-07T23:55:00+09:00',now)).toBe('어제 23:55');
 expect(relativeRecordTime('2026-09-07T15:00:00Z',now)).toBe('오늘 00:00');
 expect(relativeRecordTime('2025-07-31T23:55:00+09:00',now)).toBe('404일 전 23:55');
 expect(relativeRecordTime('2026-09-09T00:00:00+09:00',now)).toBe('내일 00:00');
 expect(relativeRecordTime('unknown',now)).toBe('unknown');
});
it('keeps approved time and selected citation identity while styling only text',()=>{
 const rows=briefRows('- **승인 완료**: 2026-09-07T23:55:00+09:00 [[ref:1]]\n- **조달 2일** [[ref:9]]',['source#component[0]'],'2026-09-08T01:00:00+09:00');
 expect(rows).toHaveLength(2);expect(rows[0].parts.find(p=>p.weight==='700').text).toBe('승인 완료');
 expect(rows[0].parts.find(p=>p.title).text).toBe('어제 23:55');
 expect(rows[0].refs[0].text).toBe('source#component[0]');expect(rows[1].refs).toEqual([]);
 expect(rows[0].refs[0].label).toBe('근거');
 expect(rows[1].parts[0].text).toBe('조달 2일');
 const raw=briefRows('- <img src=x onerror=alert(1)> **텍스트** javascript:alert(1)')[0];
 expect(raw.parts[0].text).toContain('<img');expect(raw.parts.every(p=>!('html' in p)&&!('href' in p))).toBe(true);
});

it('renders engineering units in Korean reader wording',()=>{
 expect(readableUnits('230 min, 12,650 N·m·min, 80 N·m')).toBe('230분, 12,650 뉴턴미터·분, 80 뉴턴미터');
 const rows=briefRows('공구 마모는 230 min, 과부하 지표는 12,650 N·m·min입니다.');
 expect(rows[0].parts.map(p=>p.text).join('')).toContain('230분, 과부하 지표는 12,650 뉴턴미터·분');
});

it('renders archived escaped line breaks and emphasizes the final decision condition',()=>{
 const rows=briefRows('기록을 확인했습니다.\\n현장 측정과 비교 결과가 다음 판단의 조건입니다.');
 expect(rows).toHaveLength(2);
 expect(rows[1].parts.find(p=>p.weight==='700').text).toBe('현장 측정과 비교 결과');
});
it('discloses reader source categories and preserves missing-data cautions without raw internals',()=>{
 expect(referenceLabels('closed-loop://work-order/WO-1\nRESULT#A#factor')).toEqual(['작업요청 기록','선택 설비의 진단 근거']);
 const text=readerLimitations(['demo SOP fixture',"{'owner_domain':'maintenance_readiness','status':'not_connected'}",'No matching scoped operational snapshot at the selected as-of; values withheld.']).join(' ');
 expect(text).toContain('실제 재고·조달 기간·작업 가능 시간');
 expect(text).not.toMatch(/fixture|snapshot|owner_domain|not_connected/);
});
