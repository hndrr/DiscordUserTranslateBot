import assert from 'node:assert/strict';
import { after, test, type TestContext } from 'node:test';
import { mkdtemp, mkdir, readdir, realpath, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import {
  boundedInteger, codexEnvironment, codexServerArguments, discoverSkillFiles,
  CodexTextSession, validateCodexConfiguration,
} from '../src/codex-provider.js';
import { getAgentProvider } from '../src/agent-provider.js';
import { parseBilingualDraft, parseSimilarIds, translateMessage } from '../src/translator.js';

const fixture = await realpath(await mkdtemp(path.join(tmpdir(), 'codex-rpc-test-')));
const binary = path.join(fixture, 'fake-codex');
await writeFile(binary, `#!${process.execPath}
const readline = require('node:readline');
let number = 0;
const threads = new Map();
const send = (data) => process.stdout.write(JSON.stringify(data) + '\\n');
const reply = (id, result) => send({id,result});
const notify = (method, params) => send({method,params});
readline.createInterface({input:process.stdin}).on('line', line => {
 const request = JSON.parse(line); const p=request.params||{};
 if(request.method==='initialize') return reply(request.id,{});
 if(request.method==='initialized') return;
 if(request.method==='mcpServerStatus/list') return reply(request.id,{data:process.env.CODEX_API_KEY==='fake-mcp'?[{name:'unexpected-server'}]:[],nextCursor:null});
 if(request.method==='thread/start') { const id='thread-'+(++number); threads.set(id,p); return reply(request.id,{thread:{id,ephemeral:true}}); }
 if(request.method==='thread/unsubscribe') {threads.delete(p.threadId); return reply(request.id,{});}
 if(request.method==='turn/interrupt') return reply(request.id,{});
 if(request.method!=='turn/start') return reply(request.id,{});
 const prompt=JSON.parse(p.input[0].text); const turnId='turn-'+number;
 if(prompt==='rpc-error') return send({id:request.id,error:{message:'PRIVATE_ERROR_CONTENT'}});
 if(prompt==='crash') return process.exit(7);
 if(prompt==='tool') return send({id:'server-request',method:'item/commandExecution/requestApproval',params:{}});
 const finish=()=>{
   if(prompt==='failure') {notify('turn/completed',{threadId:p.threadId,turn:{id:turnId,status:'failed'}});return;}
   let text=JSON.stringify({pid:process.pid,threadId:p.threadId,prompt,thread:threads.get(p.threadId),turn:p,env:{discordPresent:!!process.env.DISCORD_TOKEN,cursorPresent:!!process.env.CURSOR_API_KEY},args:process.argv.slice(2)});
   if(prompt==='empty') text='';
   if(prompt==='oversized') text='x'.repeat(70000);
   notify('item/completed',{threadId:p.threadId,turnId,item:{type:'agentMessage',id:'item',text:'COMMENTARY_NOT_FINAL',phase:'commentary'}});
   if(prompt!=='partial') notify('item/completed',{threadId:p.threadId,turnId,item:{type:'agentMessage',id:'final',text,phase:'final_answer'}});
   notify('turn/completed',{threadId:p.threadId,turn:{id:turnId,status:'completed'}});
 };
 if(prompt==='early') {finish();reply(request.id,{turn:{id:turnId}});return;}
 reply(request.id,{turn:{id:turnId}});
 if(prompt==='timeout') return;
 if(prompt==='delay') return setTimeout(finish,100);
 if(prompt==='stubborn') process.on('SIGTERM',()=>{});
 finish();
});
`, { mode: 0o700 });
after(() => rm(fixture, { recursive: true, force: true }));

function session(t: TestContext, extra: NodeJS.ProcessEnv = {}): CodexTextSession {
  const server = new CodexTextSession({
    PATH: process.env.PATH, CODEX_BIN: binary, CODEX_API_KEY: 'fake-test-only',
    CODEX_TIMEOUT_MS: '2000', DISCORD_TOKEN: 'discord-test-only', CURSOR_API_KEY: 'cursor-test-only',
    ...extra,
  });
  t.after(() => server.stop());
  return server;
}

test('configuration validates bounds and preserves Cursor selection', () => {
  assert.equal(getAgentProvider({}), 'cursor');
  assert.equal(getAgentProvider({ AI_PROVIDER: 'codex' }), 'codex');
  assert.throws(() => getAgentProvider({ AI_PROVIDER: 'unknown' }));
  assert.throws(() => validateCodexConfiguration({}));
  assert.throws(() => validateCodexConfiguration({ CODEX_HOME: 'relative' }));
  assert.throws(() => validateCodexConfiguration({ CODEX_API_KEY: 'test', CODEX_REASONING_EFFORT: 'unknown' }));
  for (const value of ['0','-1','1.5','9']) assert.throws(() => boundedInteger(value,2,8));
});

test('app-server has tools disabled and no paid fast mode; no host secrets are inherited', () => {
  const args=codexServerArguments(['/home/skills/test/SKILL.md']);
  assert.deepEqual(args.slice(0,2),['app-server','--stdio']);
  for(const feature of ['shell_tool','unified_exec','apps','plugins','hooks','browser_use','computer_use','image_generation','multi_agent','view_image','goals','fast_mode','apply_patch_freeform']) {
    assert.ok(args.some((arg,i)=>arg==='--disable'&&args[i+1]===feature));
  }
  assert.ok(args.includes('sandbox_mode="read-only"'));
  assert.ok(args.includes('approval_policy="never"'));
  assert.ok(args.some(arg=>arg.startsWith('skills.config=')&&arg.includes('enabled=false')));
  const env=codexEnvironment({PATH:'/bin',DISCORD_TOKEN:'secret',CURSOR_API_KEY:'secret',OTHER_SECRET:'secret'},'/fresh','/bot');
  assert.equal(env.CODEX_HOME,'/bot');assert.equal(env.HOME,'/fresh');
  assert.equal(env.DISCORD_TOKEN,undefined);assert.equal(env.CURSOR_API_KEY,undefined);assert.equal(env.OTHER_SECRET,undefined);
});

test('three calls reuse one process but use independent ephemeral conversations', async t => {
  const server=session(t);const outputs=[];
  for(const text of ['first','second','third']) outputs.push(JSON.parse(await server.run(text)));
  assert.equal(new Set(outputs.map(x=>x.pid)).size,1);
  assert.equal(new Set(outputs.map(x=>x.threadId)).size,3);
  assert.deepEqual(outputs.map(x=>x.prompt),['first','second','third']);
  for(const out of outputs){
    assert.equal(out.thread.ephemeral,true);assert.equal(out.thread.model,'gpt-6-luna');
    assert.equal(out.thread.sandbox,'read-only');assert.equal(out.thread.approvalPolicy,'never');
    assert.equal(out.turn.effort,'low');assert.equal(out.turn.serviceTierForTurn,'default');
    assert.equal(out.env.discordPresent,false);assert.equal(out.env.cursorPresent,false);
    await assert.rejects(()=>readdir(out.thread.cwd),{code:'ENOENT'});
  }
});

test('explicit none effort reaches both thread configuration and turn without a paid tier', async t => {
  const server=session(t,{CODEX_REASONING_EFFORT:'none'});
  const out=JSON.parse(await server.run('hello'));
  assert.equal(out.thread.model,'gpt-6-luna');
  assert.equal(out.thread.config.model_reasoning_effort,'none');
  assert.equal(out.turn.effort,'none');
  assert.equal(out.turn.serviceTierForTurn,'default');
});

test('stdin data stays data; early completion before RPC reply is handled', async t => {
  const server=session(t);
  const source='$(touch SHOULD_NOT_EXIST) $secret-skill 日本語';
  const out=JSON.parse(await server.run(source));
  assert.equal(out.prompt,source);assert.ok(!out.turn.input[0].text.includes('$'));
  assert.ok(!out.args.join(' ').includes(source));
  assert.equal(JSON.parse(await server.run('early')).prompt,'early');
});

test('failures, empty/partial results and oversized outputs do not return success', async t => {
  const server=session(t);
  for(const value of ['rpc-error','failure','empty','partial','oversized']) {
    await assert.rejects(server.run(value),error=>{
      assert.ok(error instanceof Error);assert.ok(!error.message.includes('PRIVATE_ERROR_CONTENT'));return true;
    });
  }
  assert.equal(JSON.parse(await server.run('recovery')).prompt,'recovery');
});

test('concurrent requests remain isolated and overload is rejected', async t => {
  const server=session(t,{CODEX_MAX_CONCURRENCY:'2'});
  const one=server.run('delay');const two=server.run('second');
  await assert.rejects(server.run('third'),/busy/);
  const [a,b]=await Promise.all([one,two]);
  assert.notEqual(JSON.parse(a).threadId,JSON.parse(b).threadId);
});

test('timeout terminates background generation and next request starts a fresh worker', async t => {
  const server=session(t,{CODEX_TIMEOUT_MS:'80'});
  await server.start();const pid=server.pid;
  await assert.rejects(server.run('timeout'),/timed out/);
  const next=JSON.parse(await server.run('next'));
  assert.notEqual(next.pid,pid);
  assert.throws(()=>process.kill(pid!,0),{code:'ESRCH'});
});

test('process crash and unexpected tool requests fail closed without replay', async t => {
  const server=session(t);
  await assert.rejects(server.run('crash'));
  assert.equal(JSON.parse(await server.run('after-crash')).prompt,'after-crash');
  await assert.rejects(server.run('tool'),/unsupported tool/);
});

test('startup failure rejects cleanly and oversized input never starts a process', async t => {
  const missing=session(t,{CODEX_BIN:path.join(fixture,'missing')});
  await assert.rejects(missing.start(),/could not start/);
  const server=session(t);
  await assert.rejects(server.run('x'.repeat(70000)),/input limit/);
  assert.equal(server.pid,undefined);
});

test('shutdown cancels work, force-reaps a stubborn child and blocks further calls', async t => {
  const server=session(t);
  await server.run('stubborn');const pid=server.pid;
  const running=server.run('timeout');const failed=assert.rejects(running);
  await delay(20);const started=Date.now();await server.stop();await failed;
  assert.ok(Date.now()-started<2500);
  assert.throws(()=>process.kill(pid!,0),{code:'ESRCH'});
  await assert.rejects(server.run('later'),/shutting down/);
});

test('runtime-created skills are disabled by filename without reading contents', async t => {
  const home=await mkdtemp(path.join(fixture,'home-'));
  const dir=path.join(home,'skills','builtins','test');await mkdir(dir,{recursive:true});
  const file=path.join(dir,'SKILL.md');await writeFile(file,'PRIVATE_CANARY',{mode:0o000});
  assert.deepEqual(await discoverSkillFiles(home),[file]);
  const server=session(t,{CODEX_API_KEY:'',CODEX_HOME:home});
  const out=JSON.parse(await server.run('hello'));
  assert.ok(out.args.some((arg:string)=>arg.includes(file)&&arg.includes('enabled=false')));
  assert.ok(!JSON.stringify(out).includes('PRIVATE_CANARY'));
  await server.stop();await symlink(dir,path.join(home,'skills','linked'));
  await assert.rejects(discoverSkillFiles(home),/symlinks/);
});

test('refuses any MCP inventory before processing a translation', async t => {
  const server=session(t,{CODEX_API_KEY:'fake-mcp'});
  await assert.rejects(server.start(),/could not start/);
  assert.equal(server.pid,undefined);
});

test('original parsing and empty translation behavior are preserved', async () => {
  assert.deepEqual(parseBilingualDraft('<<<JA>>>\nこんにちは\n<<<EN>>>\nHello'),{japanese:'こんにちは',english:'Hello'});
  assert.deepEqual(parseSimilarIds('["1","2","2"]',new Set(['1','2']),'1'),['2']);
  assert.equal(await translateMessage(' ','ja'),'（空のメッセージです）');
});
