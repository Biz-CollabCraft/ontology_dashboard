import {act} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {DemoScenarioControl} from './DemoScenarioControl';
it('renders three modes and sends a CSRF-protected selection without pretending success',async()=>{
  (globalThis as Record<string,unknown>).IS_REACT_ACT_ENVIRONMENT=true;
  const fetch=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({mode:'live',options:{normal:{observed_at:'test'},emergency:{observed_at:'test'}}})}).mockResolvedValue({ok:false});
  vi.stubGlobal('fetch',fetch);
  document.cookie='ontology_csrf=test-csrf; path=/';
  const host=document.createElement('div');document.body.append(host);const root=createRoot(host);
  try{
    await act(async()=>root.render(<DemoScenarioControl/>));
    const buttons=host.querySelectorAll('button');
    expect(buttons.length).toBe(3);
    expect(buttons[2].getAttribute('aria-pressed')).toBe('true');
    await act(async()=>buttons[1].click());
    expect(fetch.mock.calls[1][1].headers['X-CSRF-Token']).toBe('test-csrf');
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({mode:'emergency'});
    expect(host.textContent).toContain('시나리오 연결을 확인');
    expect(buttons[2].getAttribute('aria-pressed')).toBe('true');
  }finally{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();document.cookie='ontology_csrf=;max-age=0;path=/';}
});
