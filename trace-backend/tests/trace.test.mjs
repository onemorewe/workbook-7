import test from 'node:test';
import assert from 'node:assert/strict';
import {createIngest, createRead, MAX_BYTES, readQuery, redact, sha256} from '../supabase/functions/_shared/trace.mjs';

const write = 'w'.repeat(48), read = 'r'.repeat(48);
const values = {SUPABASE_URL:'https://test.supabase.co', SUPABASE_SERVICE_ROLE_KEY:'server-secret-do-not-expose',
  TRACE_WRITE_TOKENS_JSON:JSON.stringify([{device_id:'samsung-test',sha256:await sha256(write)}]),
  TRACE_READ_TOKENS_JSON:JSON.stringify([{sha256:await sha256(read)}])};
const env = key => values[key];
const event = () => ({event_id:crypto.randomUUID(), ts:Date.now(), run_id:'voice-1', session_id:'session-1', seq:2, stage:'intent-accepted', message:'Ищу Twinky в Яндекс Музыке', metadata:{}});
const request = (body, token=write, headers={}) => new Request('https://edge.test/trace-ingest', {method:'POST', headers:{'content-type':'application/json',authorization:`Bearer ${token}`,...headers},body:JSON.stringify(body)});

test('ingest denies missing/wrong/read credentials before database access', async () => {
  let calls=0;
  const handler=createIngest({env,fetcher:async()=>{calls++;return new Response(null,{status:201});}});
  for(const token of ['', 'x'.repeat(48), read]) assert.equal((await handler(request(event(),token))).status,401);
  assert.equal(calls,0);
});
test('auth configuration missing or malformed fails closed',async()=>{
  for(const config of [undefined,'{}','[]','not-json','[{"sha256":"bad"}]']) {
    const handler=createIngest({env:key=>key==='TRACE_WRITE_TOKENS_JSON'?config:values[key]});
    assert.equal((await handler(request(event()))).status,503);
  }
});
test('expired credential is rejected',async()=>{
  const handler=createIngest({env:key=>key==='TRACE_WRITE_TOKENS_JSON'?JSON.stringify([{device_id:'phone',sha256:JSON.parse(values.TRACE_WRITE_TOKENS_JSON)[0].sha256,expires_at:'2000-01-01'}]):values[key]});
  assert.equal((await handler(request(event()))).status,401);
});
test('device identity comes from auth, redacts before writing, retry uses immutable upsert',async()=>{
  let sent, url, headers;
  const handler=createIngest({env,fetcher:async(u,options)=>{url=u;headers=options.headers;sent=JSON.parse(options.body);return new Response(null,{status:201});}});
  const body={...event(),device_id:'spoofed', metadata:{access_token:'SECRET',nested:{password:'pw'},log:'{"refreshToken":"oops"}', free:write},message:`Bearer ${read} api_key="foo bar"`};
  const response=await handler(request(body));
  assert.equal(response.status,202);
  assert.equal(sent.device_id,'samsung-test');
  assert.equal(sent.client_event_id,body.event_id);
  assert.equal(sent.metadata.nested.password,'[REDACTED]');
  assert.equal(sent.metadata.access_token,'[REDACTED]');
  assert.equal(sent.metadata.free,'[REDACTED]');
  assert.ok(!JSON.stringify(sent).includes('oops'));
  assert.ok(!JSON.stringify(sent).includes('foo bar'));
  assert.equal(headers.prefer,'resolution=ignore-duplicates,return=minimal');
  assert.match(url,/on_conflict=device_id,client_event_id/);
  assert.equal(response.headers.get('access-control-allow-origin'),null);
  assert.equal(response.headers.get('cache-control'),'no-store');
});
test('invalid shapes, identifiers and numbers are rejected without database writes',async()=>{
  let calls=0; const handler=createIngest({env,fetcher:async()=>{calls++;return new Response();}});
  const bad=[null,[],{}, {...event(),event_id:'nope'},{...event(),ts:-1},{...event(),seq:1.5},{...event(),metadata:[]},{...event(),message:' '},{...event(),stage:'invalid stage'},{...event(),run_id:'a),or('},{...event(),level:'fatal'},{...event(),app_version:99}];
  for(const body of bad) assert.equal((await handler(request(body))).status,400,JSON.stringify(body));
  assert.equal(calls,0);
});
test('measures actual UTF-8 bytes when Content-Length is absent or false',async()=>{
  const handler=createIngest({env});
  const body={...event(),metadata:{bulk:'я'.repeat(MAX_BYTES)}};
  assert.equal((await handler(request(body,write,{'content-length':'2'}))).status,413);
  assert.equal((await handler(request(body))).status,413);
});
test('bounded streaming does not trust a chunked upload',async()=>{
  const stream=new ReadableStream({start(c){c.enqueue(new Uint8Array(MAX_BYTES));c.enqueue(new Uint8Array(1));c.close();}});
  const req=new Request('https://edge.test',{method:'POST',headers:{'content-type':'application/json',authorization:`Bearer ${write}`},body:stream,duplex:'half'});
  assert.equal((await createIngest({env})(req)).status,413);
});
test('content type and malformed JSON get explicit responses',async()=>{
  const handler=createIngest({env});
  assert.equal((await handler(request(event(),write,{'content-type':'text/plain'}))).status,415);
  const req=request(event()); const bad=new Request(req.url,{method:'POST',headers:req.headers,body:'{"bad"'});
  assert.equal((await handler(bad)).status,400);
});
test('database failures never disclose upstream errors or credentials',async()=>{
  for(const fetcher of [async()=>new Response('service_role=private',{status:500}),async()=>{throw new Error('server-secret-do-not-expose');}]){
    const response=await createIngest({env,fetcher})(request(event()));
    assert.equal(response.status,503);assert.ok(!(await response.text()).includes('secret'));
  }
});
test('redaction covers nested credentials, JWT, URL passwords and ordinary text remains useful',()=>{
  const result=redact({auth:{Authorization:'abc'},text:'postgresql://user:pass@db sk-testkey12345678 eyJhbGciOiJIUzI1NiJ9.payload.signature',heard:'Дотеры всегда попадают в ад',quoted:'{"apiKey":"my value"}'});
  const text=JSON.stringify(result);
  for(const secret of ['abc','pass@','testkey12345678','payload.signature','my value']) assert.ok(!text.includes(secret));
  assert.equal(result.heard,'Дотеры всегда попадают в ад');
});
test('read rejects a write token; POST/OPTIONS cannot become a read or write path',async()=>{
  const handler=createRead({env});
  assert.equal((await handler(new Request('https://edge.test',{headers:{authorization:`Bearer ${write}`}}))).status,401);
  assert.equal((await handler(new Request('https://edge.test',{method:'POST'}))).status,405);
  assert.equal((await createIngest({env})(new Request('https://edge.test',{method:'OPTIONS'}))).status,405);
});
test('read returns stable cursor preserving database microseconds',async()=>{
  const rows=[{id:crypto.randomUUID(),received_at:'2026-09-05T17:12:13.123456+00:00',message:'ok'}];
  const handler=createRead({env,fetcher:async()=>Response.json(rows)});
  const response=await handler(new Request('https://edge.test?limit=1',{headers:{authorization:`Bearer ${read}`}}));
  assert.equal(response.status,200);const data=await response.json();
  const {query}=readQuery(new URLSearchParams({cursor:data.next_cursor}));
  assert.ok(query.get('or').includes('17:12:13.123456+00:00'));
});
test('read filters are bounded, search punctuation stays a quoted literal',()=>{
  for(const params of [{limit:'2001'},{since:'bad'},{cursor:'"bad"'},{cursor:'null'},{run_id:'a),or('},{q:'x'.repeat(201)}]) assert.throws(()=>readQuery(new URLSearchParams(params)));
  const {query}=readQuery(new URLSearchParams({q:'foo),id.gt.0 "100%"'}));
  assert.equal(query.has('or'),false);
  assert.ok(query.get('message').startsWith('ilike."%'));
  assert.ok(query.get('message').includes('\\%'));
});
