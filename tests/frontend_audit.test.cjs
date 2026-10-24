const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../src/t2_bots/connect/static/app.js'),'utf8');
const station={service:'t2-connect',version:'0.3.1',api_version:1,
 runtime:{kind:'packaged',platform:'win32',sdk_version:'0.3.1',build_id:'current',compatible:true,acknowledged:true,checks:[]},
 username:'operator',role:'leader',arm:{port:'TEST'},ports:[],roles:['leader'],connected:true,
 calibrated:false,certified:false,inspection:{passed:true},capture:null,session:{status:'idle',enabled:false}};
async function workspace(state=station,initialRelease={},currentRelease=initialRelease){
 const elements={'#app':{innerHTML:''},'#toast':{hidden:true}};
 const listeners={};
 let releaseCalls=0,reloads=0;
 let stateFetch=async()=>({ok:true,json:async()=>state});
 const context=vm.createContext({
  document:{querySelector:s=>elements[s]||null,activeElement:null,addEventListener:(name,fn)=>{listeners[name]=fn;}},
  navigator:{platform:'Win32'},CSS:{escape:x=>x},console,
  location:{hostname:'127.0.0.1',origin:'http://127.0.0.1:4840',reload:()=>{reloads++;}},
  setInterval:()=>{},setTimeout:()=>{},clearTimeout:()=>{},
  fetch:async(url,options={})=>options.method==='HEAD'?{ok:true}:url==='release.json'?
    {ok:true,json:async()=>releaseCalls++?currentRelease:initialRelease}:stateFetch(url,options)
 });
 vm.runInContext(code,context);
 await new Promise(resolve=>setImmediate(resolve));
 return {run:s=>vm.runInContext(s,context),html:()=>elements['#app'].innerHTML,
         fetchState:fn=>{stateFetch=fn;},reloads:()=>reloads,elements,
         clickDataset:dataset=>listeners.click({target:{closest:()=>({dataset})},preventDefault:()=>{}}),
         click:action=>listeners.click({target:{closest:()=>({dataset:{action}})},preventDefault:()=>{}})};
}

test('users can open My arms and the directory before qualification to add their own follower',async()=>{
 const state={...station,certified:false,arms:{leader:{assigned:true,name:'Desk leader',identity:'usb-leader',connected:true,calibrated:false,certified:false},follower:{assigned:false,certified:false}},ports:[{identity:'usb-leader',port:'COM1',label:'Leader USB'}]};
 const w=await workspace(state);
 w.fetchState(async url=>({ok:true,json:async()=>url==='/api/followers'?{followers:[],configured:true}:state}));
 await w.click('dashboard');
 assert.match(w.html(),/Add my follower/);
 assert.match(w.html(),/Needs calibration/);
 assert.doesNotMatch(w.html(),/id="share-form"/);
 await w.click('arms');
 assert.match(w.html(),/Build your own pair/);
 await w.clickDataset({manageRole:'follower'});
 assert.equal(w.run('draft.role'),'follower');
 assert.equal(w.run('step'),2);
 assert.match(w.html(),/data-device="usb-leader" disabled/);
});

test('a leader owner can share their registered follower and connect to it without a second PIN prompt',async()=>{
 const arms={leader:{assigned:true,connected:true,certified:true,name:'My leader'},follower:{assigned:true,connected:true,certified:true,name:'My follower'}};
 const follower={id:'own-device',label:'Desk follower',owner:'operator',available:true,certificate:{grade:'A+',diagnostics:{bus_voltage_v:12}}};
 let current={...station,device_id:'own-device',arms,publishing:false,leader_session:{status:'idle'},follower_session:{status:'idle'}};
 const w=await workspace(current);
 w.run("route='dashboard';render()");
 assert.match(w.html(),/id="share-form"/);
 current={...current,publishing:true,follower_session:{status:'sharing',pin:'123456'}};
 let connects=0;
 w.fetchState(async(url,options)=>{
   if(url==='/api/session/connect'){
     connects++;assert.deepEqual(JSON.parse(options.body),{id:'own-device',pin:'123456'});
     current={...current,leader_session:{status:'connected',enabled:false},follower_session:{status:'connected',pin:'123456'}};
   }
   return {ok:true,json:async()=>url==='/api/followers'?{followers:[follower],configured:true}:current};
 });
 await w.run('refresh(true)');await w.run('loadDirectory()');
 assert.match(w.html(),/data-connect="own-device" >.*Connect my leader/s);
 await w.clickDataset({connect:'own-device'});
 assert.equal(connects,1);
 assert.match(w.html(),/YOUR SHARED FOLLOWER/);
 assert.match(w.html(),/YOUR LEADER SESSION/);
 assert.match(w.html(),/data-action="enable"/);
});

test('leader disconnect and follower stop sharing send independent arm scopes',async()=>{
 const current={...station,leader_session:{status:'connected'},follower_session:{status:'sharing',pin:'123456'}};
 const w=await workspace(current);const scopes=[];
 w.fetchState(async(url,options)=>{
   if(url==='/api/session/stop')scopes.push(JSON.parse(options.body).role);
   return {ok:true,json:async()=>url==='/api/followers'?{followers:[],configured:true}:current};
 });
 await w.clickDataset({stopRole:'leader'});
 await w.clickDataset({stopRole:'follower'});
 assert.deepEqual(scopes,['leader','follower']);
});

test('reference setup shows real encoder readings and an explicit start-measuring action',async()=>{
 const cap={reference_set:false,samples:1346,ranges:[{id:1,name:'shoulder_pan',position:1982,min:1982,max:1982,travel:0}]};
 const w=await workspace({...station,capture:cap});
 assert.match(w.html(),/Live encoder positions/);
 assert.match(w.html(),/1982 ticks/);
 assert.match(w.html(),/Record reference &amp; start measuring|Record reference & start measuring/);
 assert.doesNotMatch(w.html(),/0 of 6 joints measured/);
 w.elements['#ranges']={innerHTML:''};
 w.elements['#calibration-progress']={textContent:''};
 w.fetchState(async()=>({ok:true,json:async()=>({...station,capture:{...cap,ranges:[{...cap.ranges[0],position:2182}]}})}));
 await w.run('refresh()');
 assert.match(w.elements['#ranges'].innerHTML,/2182 ticks/);
 assert.match(w.elements['#calibration-progress'].textContent,/Range recording has not started/);
});

test('record-reference click starts range measurement and polling displays captured travel',async()=>{
 const ranges=Array.from({length:6},(_,i)=>({id:i+1,name:'joint_'+i,position:2000,min:2000,max:2000,travel:0}));
 let current={...station,capture:{reference_set:false,ranges}};
 const w=await workspace(current);
 let recorded=false;
 w.fetchState(async(url,options)=>{
   if(url==='/api/calibration/reference'){
     assert.equal(options.method,'POST');recorded=true;
     current={...current,capture:{reference_set:true,ranges}};
   }
   return {ok:true,json:async()=>current};
 });
 await w.click('reference');
 assert.equal(recorded,true);
 assert.match(w.html(),/Measuring joint travel/);
 assert.match(w.html(),/0 of 6 joints measured/);
 w.elements['#ranges']={innerHTML:''};
 current={...current,capture:{reference_set:true,ranges:ranges.map(r=>({...r,position:2100,min:1900,max:2100,travel:200}))}};
 await w.run('refresh()');
 assert.match(w.html(),/6 of 6 joints measured/);
 assert.match(w.elements['#ranges'].innerHTML,/200 ticks/);
 assert.doesNotMatch(w.html(),/data-action="save-calibration" disabled/);
});

test('motor fault pauses in place and a healthy recheck continues the existing measurements',async()=>{
 const ranges=Array.from({length:6},(_,i)=>({id:i+1,name:'joint_'+i,position:2200,min:2000,max:2200,travel:200}));
 let current={...station,capture:{reference_set:true,ranges}};
 const w=await workspace(current);
 current={...current,capture:{...current.capture,paused_error:'Motor 2 (shoulder lift) reports status 0x10, 5.3 V, 28 °C.'}};
 w.fetchState(async(url,options)=>{
   if(url==='/api/calibration/resume'){
     assert.equal(options.method,'POST');
     current={...current,capture:{...current.capture,paused_error:''}};
   }
   return {ok:true,json:async()=>url==='/api/calibration/resume'?current.capture:current};
 });
 await w.run('refresh()');
 assert.match(w.html(),/Calibration paused/);
 assert.match(w.html(),/status 0x10/);
 assert.match(w.html(),/Recheck motors &amp; continue/);
 assert.match(w.html(),/200 ticks/);
 assert.match(w.html(),/data-action="save-calibration" disabled/);
 assert.doesNotMatch(w.html(),/Start guided calibration/);
 await w.click('resume-calibration');
 assert.doesNotMatch(w.html(),/Calibration paused/);
 assert.match(w.html(),/6 of 6 joints measured/);
 assert.doesNotMatch(w.html(),/data-action="save-calibration" disabled/);
});
test('an old local page reloads once after verifying the updated companion manifest',async()=>{
 const w=await workspace(station,{version:'0.3.1',build_id:'previous'},{version:'0.3.1',build_id:'current'});
 assert.equal(w.reloads(),1);
 await w.run('refresh(true)');
 assert.equal(w.reloads(),1);
});
test('a genuinely older companion does not trigger an automatic reload loop',async()=>{
 const w=await workspace({...station,runtime:{...station.runtime,build_id:'previous'}},
   {version:'0.3.1',build_id:'current'});
 assert.equal(w.reloads(),0);
 assert.equal(w.run('online'),false);
});
test('a forced post-action refresh waits for the in-flight poll then reads fresh state',async()=>{
 const w=await workspace();
 let finish,calls=0;
 const deferred=new Promise(resolve=>{finish=resolve;});
 w.fetchState(async()=>{calls++;return calls===1?deferred:{ok:true,json:async()=>({...station,calibrated:true})};});
 const poll=w.run('refresh()');
 const actionRefresh=w.run('refresh(true)');
 finish({ok:true,json:async()=>station});
 await Promise.all([poll,actionRefresh]);
 assert.equal(calls,2);
 assert.equal(w.run('state.calibrated'),true);
 assert.equal(w.run('step'),5);
});
test('calibration save requires a reference and measured travel on all six joints',async()=>{
 const names=['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper'];
 const ranges=names.map((name,i)=>({id:i+1,name,travel:i===5?119:120}));
 const w=await workspace({...station,capture:{reference_set:true,ranges}});
 assert.match(w.html(),/data-action="save-calibration" disabled/);
 assert.match(w.html(),/5 of 6 joints/);
 w.fetchState(async()=>({ok:true,json:async()=>({...station,capture:{reference_set:true,ranges:ranges.map(r=>({...r,travel:120}))}})}));
 await w.run('refresh(true)');
 assert.doesNotMatch(w.html(),/data-action="save-calibration" disabled/);
 assert.match(w.html(),/6 of 6 joints/);
});
test('an active source runtime does not create another download loop',async()=>{
 const w=await workspace({...station,runtime:{...station.runtime,kind:'source',acknowledged:false}},
   {version:'0.3.1',build_id:'current',windows_signing_required:true});
 assert.match(w.html(),/source runtime is already running/);
 assert.doesNotMatch(w.html(),/has not been published|Download Python if needed/);
 assert.match(w.html(),/trusted code signing/);
});
