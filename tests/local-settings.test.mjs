import test from 'node:test';
import { request } from 'node:http';
import assert from 'node:assert/strict';
import { mkdtemp, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createApp } from '../server/index.mjs';
import { loadLocalSettings } from '../server/local-settings.mjs';
async function serve(t, options={}) {
  const dir=await mkdtemp(join(tmpdir(),'yueding-test-'));
  const path=join(dir,'.local-dify.json');
  const app=createApp({env:{},localConfigPath:path,...options});
  await new Promise(resolve=>app.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{app.closeAllConnections();await new Promise(resolve=>app.close(resolve));await rm(dir,{recursive:true,force:true});});
  return {base:`http://127.0.0.1:${app.address().port}`,path};
}
const post=(base,token,keys,extra={})=>fetch(`${base}/api/local-settings`,{method:'POST',headers:{Origin:base,'Content-Type':'application/json','X-Local-Setup-Token':token,...extra},body:JSON.stringify({keys})});
test('local setup validates workflow without upload, saves private file, reloads, never returns keys',async t=>{
  let calls=0;
  const {base,path}=await serve(t,{fetch:async(url,options)=>{
    calls++;assert.ok(url.endsWith('/parameters'));assert.equal(options.headers.Authorization,'Bearer synthetic-key');
    return Response.json({user_input_form:[{file:{variable:'lease_file'}},{'text-input':{variable:'goal'}}]});
  }});
  const setup=await(await fetch(`${base}/api/local-settings`)).json();
  assert.equal(setup.configured.rental,false);
  const saved=await post(base,setup.token,{rental:'synthetic-key'});assert.equal(saved.status,200);
  assert.ok(!(await saved.text()).includes('synthetic-key'));assert.equal(calls,1);
  assert.equal((await stat(path)).mode&0o777,0o600);
  assert.equal((await loadLocalSettings(path)).DIFY_RENTAL_API_KEY,'synthetic-key');
  const config=await(await fetch(`${base}/api/config`)).json();assert.equal(config.scenarios.rental,true);assert.equal(config.localSetup,true);
  assert.ok(!(await(await fetch(`${base}/api/local-settings`)).text()).includes('synthetic-key'));
  for(const name of ['/.local-dify.json','/.env']) assert.equal((await fetch(base+name)).status,404);
});
test('invalid key and mismatched application are rejected without changing configuration',async t=>{
  let mode='invalid';
  const {base,path}=await serve(t,{env:{DIFY_RENTAL_API_KEY:'existing'},fetch:async()=>mode==='invalid'?new Response('',{status:401}):Response.json({user_input_form:[]})});
  const {token}=await(await fetch(`${base}/api/local-settings`)).json();
  assert.equal((await post(base,token,{rental:'new-key'})).status,400);
  mode='mismatch';assert.equal((await post(base,token,{rental:'new-key'})).status,400);
  assert.deepEqual(await loadLocalSettings(path),{});
  assert.equal((await(await fetch(`${base}/api/config`)).json()).scenarios.rental,true);
});
test('local setup rejects cross-origin, forged token and non-loopback Host',async t=>{
  const {base}=await serve(t,{fetch:()=>{throw Error('unexpected request')}});
  const {token}=await(await fetch(`${base}/api/local-settings`)).json();
  assert.equal((await post(base,'wrong',{rental:'key'})).status,403);
  assert.equal((await post(base,token,{rental:'key'},{Origin:'https://evil.invalid'})).status,403);
  const forgedStatus=await new Promise((resolve,reject)=>{const req=request(`${base}/api/local-settings`,{headers:{Host:'evil.invalid'}},res=>{res.resume();resolve(res.statusCode);});req.on('error',reject);req.end();});
  assert.equal(forgedStatus,404);
  const remote=await serve(t,{localConfigPath:undefined});
  assert.equal((await fetch(`${remote.base}/api/local-settings`)).status,404);
});
