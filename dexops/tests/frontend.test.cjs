const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../src/t2_bots/connect/static/app.js'),'utf8');
const index=fs.readFileSync(path.join(__dirname,'../src/t2_bots/connect/static/index.html'),'utf8');
const favicon=fs.readFileSync(path.join(__dirname,'../src/t2_bots/connect/static/favicon.svg'),'utf8');

test('Dexops identity uses a text wordmark, home path, and D favicon',()=>{
  assert.match(index,/<title>Dexops —/);
  assert.match(favicon,/>D<\/text>/);
  assert.doesNotMatch(favicon,/<circle|<path/);
  assert.match(source,/aria-label="Dexops home"/);
  assert.match(source,/data-action="home">\$\{icon\('home'\)\}Home/);
});

async function workspace(runtime=null,releaseInfo={},hostname='localhost',storage=new Map()){
  const elements={'#app':{innerHTML:''},'#toast':{hidden:true}};
  const requests=[],calls=[];
  const context=vm.createContext({
    document:{querySelector:s=>elements[s]||null,activeElement:null,addEventListener:()=>{}},
    navigator:{platform:'Win32'},location:{hostname,reload:()=>{}},CSS:{escape:x=>x},
    localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},
    setInterval:()=>{},setTimeout:()=>{},clearTimeout:()=>{},console,
    fetch:async (url,options={})=>{requests.push(url);calls.push({url,options});if(url.endsWith('runtime/confirm')&&runtime)runtime={...runtime,runtime:{...runtime.runtime,acknowledged:true}};return options.method==='HEAD'?{ok:true}:url==='release.json'?{ok:true,json:async()=>releaseInfo}:runtime?{ok:true,json:async()=>runtime}:{ok:false,json:async()=>({detail:'No local companion'})};}
  });
  vm.runInContext(source,context);
  await new Promise(resolve=>setImmediate(resolve));
  return {run:s=>vm.runInContext(s,context),html:()=>elements['#app'].innerHTML,requests,calls,setRuntime:value=>{runtime=value;}};
}

test('deployed origins stay on the hosted page and call the loopback API',async()=>{
  for(const host of ['play.trydexops.com','servosocialruss.vercel.app']){
    const w=await workspace(null,{},host);
    assert.ok(w.requests.includes('http://127.0.0.1:4840/api/state'));
    assert.doesNotMatch(w.html(),/href="http:\/\/127\.0\.0\.1:4840/);
    assert.match(w.html(),/This page reconnects automatically/);
    assert.doesNotMatch(w.html(),/data-action="connect-companion"/);
  }
});

test('deployed workspace replaces a stale localhost directory with the shared directory',async()=>{
  const runtime={...station,directory_url:'http://127.0.0.1:8090'};
  const directory='https://servo-social-russ-1.onrender.com';
  const w=await workspace(runtime,{version:'0.3.1',build_id:'test-build',directory_url:directory},'servosocialruss.vercel.app');
  const migration=w.calls.find(call=>call.url==='http://127.0.0.1:4840/api/identity');
  assert.ok(migration);
  assert.deepEqual(JSON.parse(migration.options.body),{username:'orbit',directory_url:directory});
});

test('hosted entry offers honest installation without invented releases',async()=>{
  const w=await workspace();
  assert.match(w.html(),/aria-label="Dexops home"/);
  assert.match(w.html(),/>Dexops</);
  assert.match(w.html(),/data-action="home">.*Home/);
  assert.doesNotMatch(w.html(),/brand-mark|t₂|t2 CONNECT/);
  assert.match(w.html(),/A small install/);
  assert.match(w.html(),/has not been published/);
  assert.doesNotMatch(w.html(),/Download for Windows/);
  assert.match(w.html(),/No companion verified/);
});

test('no helper cannot advance onboarding',async()=>{
  const w=await workspace();w.run('go(3)');
  assert.match(w.html(),/STEP 1 OF 5/);
});

const station={service:'t2-connect',version:'0.3.1',api_version:1,
  runtime:{kind:'packaged',platform:'win32',sdk_version:'0.3.1',build_id:'test-build',python_version:'3.12.14',compatible:true,acknowledged:true,checks:[]},
  session_token:'test-only',username:'orbit',
  role:'leader',arm:{port:'TEST'},ports:[],connected:false,calibrated:false,roles:['leader'],
  session:{status:'idle',enabled:false}};

test('empty directory is actionable and has no fake followers',async()=>{
  const w=await workspace();w.run(`online=true;state=${JSON.stringify(station)};route='dashboard';render()`);
  assert.match(w.html(),/No followers are shared right now/);
  assert.doesNotMatch(w.html(),/data-connect=/);
});

test('user supplied directory labels are escaped',async()=>{
  const w=await workspace();
  w.run(`online=true;state=${JSON.stringify({...station,calibrated:true,connected:true})};route='dashboard';followers=[{id:'device',owner:'owner',label:'<img src=x onerror=alert(1)>',available:true,calibrated:true}];render()`);
  assert.doesNotMatch(w.html(),/<img src=x/);
  assert.match(w.html(),/&lt;img/);
});

test('connect-only session exposes explicit enable and stop',async()=>{
  const w=await workspace();
  w.run(`online=true;state=${JSON.stringify({...station,calibrated:true,session:{status:'connected',enabled:false}})};route='dashboard';render()`);
  assert.match(w.html(),/movement is not enabled/);
  assert.match(w.html(),/data-action="enable"/);
  assert.match(w.html(),/data-stop-role="leader"/);
});

test('a stale service cannot mark installation complete',async()=>{
  const w=await workspace({...station,version:'0.2.0'});
  assert.equal(w.run('online'),false);
  assert.match(w.html(),/Update (the )?companion/i);
  assert.match(w.html(),/STEP 1 OF 5/);
});

test('unverified source runtime stays on installation step',async()=>{
  const w=await workspace({...station,version:'0.3.1',api_version:1,
    runtime:{kind:'source',sdk_version:'0.3.1',python_version:'3.12.14',compatible:true,acknowledged:false,checks:[]}});
  assert.match(w.html(),/STEP 1 OF 5/);
  assert.doesNotMatch(w.html(),/Your companion is connected/);
  assert.match(w.html(),/source/i);
});

test('runtime and SDK mismatch is rejected',async()=>{
  const w=await workspace({...station,runtime:{...station.runtime,sdk_version:'0.2.0'}});
  assert.equal(w.run('online'),false);
  assert.match(w.html(),/SDK or its required components do not match/);
});

test('compatible source build differences do not force another installation',async()=>{
  const w=await workspace(station,{version:'0.3.1',build_id:'new-build'});
  assert.equal(w.run('online'),true);
  assert.doesNotMatch(w.html(),/different build|Update the companion/);
});

test('all supported platforms retain specific installation guidance',async()=>{
  const w=await workspace(null,{source:'downloads/source.zip'});
  for(const os of ['windows','macos','linux']){
    w.run(`draft.platform='${os}';render()`);
    assert.match(w.html(),new RegExp(`data-platform="${os}" aria-pressed="true"`));
    assert.match(w.html(),/Python 3.10\+/);
    assert.match(w.html(),/Git/);
  }
  w.run("draft.platform='macos';render()");
  assert.match(w.html(),/macOS · set up once/);
  assert.match(w.html(),/python3 dexops\/scripts\/setup-dexops.py/);
  w.run("draft.platform='linux';render()");
  assert.match(w.html(),/Linux · set up once/);
});

test('current source runtime can be confirmed without claiming a download happened',async()=>{
  const w=await workspace({...station,runtime:{...station.runtime,kind:'source',acknowledged:false}});
  assert.match(w.html(),/does not mean you downloaded or installed/);
  assert.match(w.html(),/Use this verified source runtime/);
  assert.match(w.html(),/STEP 1 OF 5/);
});

test('running package offers reuse and maintenance rather than another download',async()=>{
  const w=await workspace({...station,runtime:{...station.runtime,acknowledged:false}},
    {version:'0.3.1',build_id:'test-build',windows:null,source:null});
  assert.match(w.html(),/Your companion is running. No new download is needed/);
  assert.doesNotMatch(w.html(),/download>.*Windows/);
  assert.match(w.html(),/Confirm this companion/);
  assert.match(w.html(),/STEP 1 OF 5/);
});

test('installed package only satisfies prerequisites for its own operating system',async()=>{
  const w=await workspace({...station,runtime:{...station.runtime,acknowledged:false}});
  w.run("draft.platform='macos';render()");
  assert.match(w.html(),/macOS · set up once/);
  assert.match(w.html(),/Python 3.10\+/);
  assert.doesNotMatch(w.html(),/This macOS companion is already running/);
});

test('temporary runtime loss clears its warning after a successful reconnect',async()=>{
  const w=await workspace(station);
  w.setRuntime(null);
  await w.run('refresh(true)');
  assert.match(w.html(),/local runtime stopped responding/);
  w.setRuntime(station);
  await w.run('refresh(true)');
  assert.equal(w.run('online'),true);
  assert.doesNotMatch(w.html(),/local runtime stopped responding/);
});

test('reconnecting preserves an unrelated action error',async()=>{
  const w=await workspace(station);
  w.run("failure='That username is taken.'");
  w.setRuntime(null);
  await w.run('refresh(true)');
  w.setRuntime(station);
  await w.run('refresh(true)');
  assert.match(w.html(),/That username is taken/);
});

test('inspection remains a completed step while the user prepares calibration',async()=>{
  const w=await workspace({...station,connected:true,inspection:{passed:true,at:Date.now()/1000-120}});
  assert.equal(w.run('step'),4);
  await w.run('refresh(true)');
  assert.equal(w.run('step'),4);
});

test('a stopped capture explains the failure on calibration instead of returning to inspection',async()=>{
  const w=await workspace({...station,connected:true,capture:null,capture_error:'Encoder read failed. Reconnect and restart calibration.'});
  assert.equal(w.run('step'),4);
  assert.match(w.html(),/Encoder read failed/);
  assert.match(w.html(),/Start guided calibration/);
});

test('recalibration stays on capture even when an older saved profile exists',async()=>{
  const w=await workspace({...station,connected:true,calibrated:true,capture:{reference_set:false,ranges:[]}});
  assert.equal(w.run('step'),4);
});

const gitRelease={version:'0.3.1',api_version:1,minimum_companion_version:'0.3.1',
  installation:{strategy:'git',repository:'https://github.com/RussMaharic/servo_social_russ.git',commit:'a'.repeat(40),bootstrap:'bootstrap.py'}};

test('new-user setup uses the current hosted origin on every operating system',async()=>{
  const w=await workspace(null,gitRelease,'play.trydexops.com');
  assert.match(w.html(),/Invoke-WebRequest/);
  assert.match(w.html(),/https:\/\/play.trydexops.com\/bootstrap.py/);
  assert.match(w.html(),/--autostart/);
  assert.doesNotMatch(w.html(),/ExecutionPolicy|Bypass|Download updated|\.zip/);
  for(const os of ['macos','linux']){
    w.run(`draft.platform='${os}';render()`);
    assert.match(w.html(),/curl --fail --location/);
    assert.match(w.html(),/python3/);
  }
  w.run('draft.autostart=false;render()');
  assert.match(w.html(),/--no-autostart/);
});

test('step one shows setup, start and update commands expanded for new and returning users',async()=>{
  for(const returning of [false,true]){
    const w=await workspace(null,gitRelease,'servosocialruss.vercel.app',new Map(returning?[['dexops.installed','yes']]:[]));
    assert.match(w.html(),/STEP 1 OF 5/);
    for(const id of ['install-command','start-command','update-command']){
      assert.match(w.html(),new RegExp(`id="${id}" open`));
    }
    for(const command of ['dexops','dexops update','dexops doctor']){
      assert.match(w.html(),new RegExp(`data-copy="${command}"`));
    }
    assert.match(w.html(),/Invoke-WebRequest/);
  }
});

test('a remembered stopped installation offers start without claiming a connection',async()=>{
  const w=await workspace(null,gitRelease,'servosocialruss.vercel.app',new Map([['dexops.installed','yes']]));
  assert.match(w.html(),/This browser has connected before/);
  assert.match(w.html(),/Already set up\? Start your existing installation/);
  assert.equal(w.run('online'),false);
  assert.equal(w.run('step'),0);
  assert.ok(w.requests.every(url=>!url.endsWith('runtime/confirm')));
});

test('compatible hosted source automatically verifies then resumes username',async()=>{
  const w=await workspace({...station,username:'',runtime:{...station.runtime,kind:'source',acknowledged:false}},
    {...gitRelease,build_id:'different-ui-build'},'servosocialruss.vercel.app');
  assert.equal(w.run('setupReady()'),true);
  assert.equal(w.run('step'),1);
  assert.match(w.html(),/What should we call you/);
  assert.ok(w.calls.some(call=>call.url.endsWith('runtime/confirm')));
  assert.ok(w.calls.every(call=>!/(session\/enable|arm|calibration\/start)$/.test(call.url)));
});

test('minimum companion version and capabilities gate real incompatibilities',async()=>{
  const supported=await workspace(station,{...gitRelease,version:'0.4.0'});
  assert.equal(supported.run('online'),true);
  const missing=await workspace(station,{...gitRelease,required_capabilities:['new_protocol']});
  assert.equal(missing.run('online'),false);
  assert.match(missing.html(),/dexops update/);
  const old=await workspace(station,{...gitRelease,minimum_companion_version:'0.4.0'});
  assert.equal(old.run('online'),false);
});

test('returning hosted calibrated station resumes dashboard without redoing setup or enabling movement',async()=>{
  const runtime={...station,connected:true,calibrated:true,arms:{leader:{assigned:true,connected:true,calibrated:true}},
    runtime:{...station.runtime,kind:'source',acknowledged:false}};
  const w=await workspace(runtime,gitRelease,'servosocialruss.vercel.app');
  assert.equal(w.run('route'),'dashboard');
  assert.ok(w.calls.every(call=>!/(session\/enable|inspect|calibration\/start)$/.test(call.url)));
});
