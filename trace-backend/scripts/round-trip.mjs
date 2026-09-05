// Run only against an authorized project. Logs evidence, never credentials/trace content.
import assert from 'node:assert/strict';
const {TRACE_INGEST_URL, TRACE_READ_URL, TRACE_WRITE_TOKEN, TRACE_READ_TOKEN} = process.env;
assert.ok([TRACE_INGEST_URL,TRACE_READ_URL,TRACE_WRITE_TOKEN,TRACE_READ_TOKEN].every(Boolean), 'Missing trace endpoint/credential environment');
const run_id=`smoke-${crypto.randomUUID()}`, event_id=crypto.randomUUID();
const body={event_id,run_id,stage:'smoke',message:`Private trace round trip ${run_id}`,ts:Date.now(),metadata:{access_token:'synthetic-must-be-redacted'}};
const send=token=>fetch(TRACE_INGEST_URL,{method:'POST',headers:{authorization:`Bearer ${token}`,'content-type':'application/json'},body:JSON.stringify(body)});
assert.equal((await send('wrong-token-that-has-at-least-thirty-two-chars')).status,401);
for(let i=0;i<2;i++) assert.equal((await send(TRACE_WRITE_TOKEN)).status,202);
const url=new URL(TRACE_READ_URL);url.searchParams.set('run_id',run_id);
assert.equal((await fetch(url)).status,401);
assert.equal((await fetch(url,{headers:{authorization:`Bearer ${TRACE_WRITE_TOKEN}`}})).status,401);
assert.equal((await send(TRACE_READ_TOKEN)).status,401);
const result=await fetch(url,{headers:{authorization:`Bearer ${TRACE_READ_TOKEN}`}});
assert.equal(result.status,200);const {events}=await result.json();
assert.equal(events.length,1);assert.equal(events[0].client_event_id,event_id);
assert.equal(events[0].metadata.access_token,'[REDACTED]');
console.log(JSON.stringify({ok:true,run_id,event_id,checks:['write-auth','read-auth','scope-isolation','insert-read','retry-dedup','redaction']}));
