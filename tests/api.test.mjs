import test from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from '../server/index.mjs';
import { readSSE } from '../sse.mjs';

const env = { DIFY_RENTAL_API_KEY: 'test-rental', DIFY_EMPLOYMENT_API_KEY: 'test-employment', DIFY_PRIVACY_API_KEY: 'test-privacy' };
function form(scenario='rental') {
  const data = new FormData(); data.set('file', new Blob(['Synthetic contract only.']), 'sample.txt');
  data.set('scenario', scenario); data.set('question', '能否打孔？'); data.set('context', '补充背景'); data.set('priority', '两者平衡'); return data;
}
function stream(events, crlf=false) {
  const wire = 'event: ping\n\n' + events.map(data => 'data: ' + JSON.stringify(data) + '\n\n').join('');
  const bytes = new TextEncoder().encode(crlf ? wire.replace(/\n/g, '\r\n') : wire);
  return new ReadableStream({ start(controller) { for(let i=0;i<bytes.length;i+=7) controller.enqueue(bytes.slice(i,i+7)); controller.close(); } });
}
async function serve(t, options={}) {
  const app = createApp({ env, ...options });
  await new Promise(resolve => app.listen(0, '127.0.0.1', resolve));
  t.after(() => { app.closeAllConnections(); return new Promise(resolve=>app.close(resolve)); });
  return `http://127.0.0.1:${app.address().port}`;
}
const collect = async response => { const events=[]; for await(const event of readSSE(response.body)) events.push(event); return events; };

test('all scenarios upload and run with matching identity, key and correct file input; only final reviewed result is exposed', async t => {
  for(const scenario of ['rental','employment','privacy']) {
    let uploadUser; let uploadKey; let calls=0;
    const base = await serve(t, { fetch: async (url, options) => {
      calls++;
      if(url.endsWith('/files/upload')) {
        uploadUser=options.body.get('user'); uploadKey=options.headers.Authorization;
        assert.equal(options.body.get('file').name, 'document.txt');
        return Response.json({id:'file-123'},{status:201});
      }
      assert.ok(url.endsWith('/workflows/run'));
      const body=JSON.parse(options.body); assert.equal(body.user,uploadUser); assert.equal(options.headers.Authorization,uploadKey);
      assert.equal(uploadKey,`Bearer test-${scenario}`); assert.equal(body.response_mode,'streaming');
      const field={rental:'lease_file',employment:'employment_file',privacy:'policy_file'}[scenario];
      assert.equal(body.inputs[field].upload_file_id,'file-123');
      assert.ok(JSON.stringify(body.inputs).includes('能否打孔？'));
      return new Response(stream([
        {event:'node_started',data:{node_type:'llm',node_id:'analysis'}},
        {event:'text_chunk',data:{text:'UNREVIEWED TEXT'}},
        {event:'node_started',data:{node_type:'llm',node_id:'review'}},
        {event:'workflow_finished',data:{status:'succeeded',outputs:{result:'## 核对结果\n请先取得书面同意。'}}}
      ],true),{headers:{'Content-Type':'text/event-stream'}});
    }});
    const response=await fetch(`${base}/api/analyze`,{method:'POST',body:form(scenario)});
    assert.equal(response.status,200); const events=await collect(response);
    assert.equal(events.at(-1).event,'result'); assert.match(events.at(-1).data.answer,/书面同意/);
    assert.ok(events.some(x=>x.data.stage==='review')); assert.ok(!JSON.stringify(events).includes('UNREVIEWED'));
    assert.ok(!JSON.stringify(events).includes('test-rental')); assert.equal(calls,2);
  }
});
test('API key absence and public health never expose secrets or trigger upstream calls',async t=>{
  const base=await serve(t,{env:{},fetch:()=>{throw Error('unexpected request')}});
  const config=await (await fetch(`${base}/api/config`)).json(); assert.equal(config.scenarios.rental,false);
  assert.equal((await fetch(`${base}/api/analyze`,{method:'POST',body:form()})).status,503);
  assert.equal((await fetch(`${base}/.env`)).status,404);
});
test('access code, cross-origin requests, file types and oversized requests are rejected',async t=>{
  const base=await serve(t,{env:{...env,DEMO_ACCESS_CODE:'fixture-code'},fetch:()=>{throw Error('unexpected request')}});
  assert.equal((await fetch(`${base}/api/analyze`,{method:'POST',body:form()})).status,401);
  assert.equal((await fetch(`${base}/api/analyze`,{method:'POST',headers:{Origin:'https://untrusted.example'},body:form()})).status,403);
  const bad=form(); bad.set('file',new Blob(['x']),'bad.html');
  assert.equal((await fetch(`${base}/api/analyze`,{method:'POST',headers:{'X-Demo-Code':'fixture-code'},body:bad})).status,400);
  const large=form(); large.set('file',new Blob([new Uint8Array(15*1024*1024+1)]),'large.pdf');
  assert.equal((await fetch(`${base}/api/analyze`,{method:'POST',headers:{'X-Demo-Code':'fixture-code'},body:large})).status,413);
});
test('upstream failed or truncated streams cannot become a successful answer', async t=>{
  for(const events of [[],[{event:'workflow_finished',data:{status:'failed',error:'SECRET-UPSTREAM-DETAIL'}}],[{event:'workflow_finished',data:{status:'succeeded',outputs:{}}}]]) {
    const base=await serve(t,{fetch:async url=>url.endsWith('/files/upload')?Response.json({id:'file-1'}):new Response(stream(events))});
    const frames=await collect(await fetch(`${base}/api/analyze`,{method:'POST',body:form()}));
    assert.equal(frames.at(-1).event,'error'); assert.ok(!frames.some(x=>x.event==='result'));
    assert.ok(!JSON.stringify(frames).includes('SECRET-UPSTREAM-DETAIL'));
  }
});
test('upload authentication errors remain errors and hide upstream response',async t=>{
  const base=await serve(t,{fetch:async()=>new Response('SECRET-UPSTREAM-DETAIL',{status:401})});
  const events=await collect(await fetch(`${base}/api/analyze`,{method:'POST',body:form()}));
  assert.equal(events.at(-1).event,'error'); assert.match(events.at(-1).data.message,/认证失败/);
  assert.ok(!JSON.stringify(events).includes('SECRET-UPSTREAM-DETAIL'));
});
