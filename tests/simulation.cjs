'use strict'
const test=require('node:test'),assert=require('node:assert/strict'),E=require('../static/js/engine.js')
const config={duration:2,ai_count:8,death_penalty:20}
test('100 identical replays yield exactly identical state',()=>{const input=[[0,100,0],[12,0,100],[30,-100,-100]],result=E.replay(123,config,input);for(let i=0;i<100;i++)assert.deepEqual(E.replay(123,config,input),result)})
test('PRNG and default eight opponents',()=>{const a=new E.RNG(9),b=new E.RNG(9);for(let i=0;i<100;i++)assert.equal(a.next(),b.next());assert.equal(E.make(9).holes.length,9)})
test('bounded, ordered integer input and config',()=>{for(const input of [[[0,101,0]],[[0,.1,0]],[[1,0,0],[1,1,0]],[[40,0,0]],[[0,0]],'score'])assert.throws(()=>E.replay(1,config,input));assert.throws(()=>E.make(1,{duration:99999}));assert.throws(()=>E.make(1,{ai_count:99999}))})
test('consumption, growth and obstructed respawns',()=>{const s=E.make(2,{duration:120,ai_count:0});s.objects=[{id:0,type:0,x:2400,y:2400,homeX:2400,homeY:2400,ready:0,variant:0}];E.step(s);assert.equal(s.holes[0].score,4);assert.ok(s.holes[0].radius>22);s.objects[0].ready=s.tick+1;E.step(s);assert.equal(s.objects[0].ready,s.tick+20);s.holes[0].x=500;s.holes[0].y=500;for(let i=0;i<20;i++)E.step(s);assert.equal(s.objects[0].ready,0)})
test('human and AI consumption, death penalty, respawn',()=>{for(const attacker of [0,1]){const s=E.make(2,{duration:120,ai_count:1});s.objects=[];const h=s.holes[attacker],v=s.holes[1-attacker];h.radius=100;h.mass=500;v.score=100;v.x=h.x;v.y=h.y;E.step(s);assert.equal(v.score,80);assert.equal(v.deaths,1);assert.ok(h.score>0);for(let i=0;i<60;i++)E.step(s);assert.equal(v.deadUntil,0);assert.equal(v.radius,22)}})
test('ticks stop at duration; replay matches live state',()=>{const s=E.make(7,config);for(let i=0;i<100;i++)E.step(s,[100,0]);assert.equal(s.tick,40);const p=s.holes[0];assert.deepEqual(E.replay(7,config,[[0,100,0]]),{score:p.score,mass:p.mass,radius:p.radius,x:p.x,y:p.y,deaths:p.deaths,ticks:40})})
test('pavement objects remain fully off roads at spawn and respawn',()=>{
 const types=new Set([1,3,5,6,7,8])
 function check(o){if(!types.has(o.type))return;const x=o.x%300,y=o.y%300,r=E.TYPES[o.type].size;assert.ok(x-r>=63&&x+r<=299&&y-r>=63&&y+r<=299);assert.ok(x+r<=120||x-r>=244||y+r<=120||y-r>=244)}
 for(let seed=1;seed<=20;seed++){const s=E.make(seed,{duration:120,ai_count:0});s.objects.forEach(check);s.holes=[];for(let round=0;round<4;round++){s.objects.forEach(o=>o.ready=s.tick+1);E.step(s);s.objects.forEach(check)}}
})
test('growth ring uses exact mass boundaries of displayed sizes',()=>{
 assert.deepEqual(E.growthProgress(0),{size:1,fraction:0});assert.deepEqual(E.growthProgress(125),{size:2,fraction:0})
 assert.equal(E.growthProgress(124).size,1);assert.ok(E.growthProgress(124).fraction>.99)
 assert.equal(E.growthProgress(312).size,2);assert.ok(Math.abs(E.growthProgress(312).fraction-.5)<.01)
 assert.deepEqual(E.growthProgress(500),{size:3,fraction:0})
 for(let mass=0;mass<10000;mass++){const p=E.growthProgress(mass);assert.ok(p.fraction>=0&&p.fraction<1)}
})
test('merged districts, terraces, large landmarks and rare valuable coins',()=>{
 for(let seed=1;seed<=30;seed++){const s=E.make(seed);assert.deepEqual(s.layout,E.makeLayout(seed));assert.ok(s.layout.regions.length>=18);assert.ok(s.layout.regions.reduce((n,r)=>n+r.w*r.h,0)>=100);assert.ok(s.layout.regions.every(r=>r.w>=2&&r.h>=1));const heights=s.objects.filter(o=>o.height).map(o=>o.height);assert.ok(Math.min(...heights)<40);assert.ok(Math.max(...heights)>500);assert.ok(s.objects.some(o=>o.type===14));assert.ok(s.objects.some(o=>o.type===16));assert.equal(s.objects.filter(o=>o.type===4).length,24);assert.equal(E.TYPES[4].score,120);assert.ok(s.objects.some(o=>o.parked));}
})
test('traffic remains on uninterrupted road lanes through movement and respawn',()=>{
 for(let seed=1;seed<=10;seed++){const s=E.make(seed,{ai_count:0});s.holes=[];const cars=s.objects.filter(o=>o.traffic),before=cars.map(o=>[o.x,o.y]),moved=new Set();for(let t=0;t<500;t++){if(t===100)cars.forEach(o=>o.ready=s.tick+1);E.step(s);for(const o of cars){if(o.x!==before[cars.indexOf(o)][0]||o.y!==before[cars.indexOf(o)][1])moved.add(o.id);assert.equal(o[o.axis?'x':'y'],o.lane);assert.ok(!s.layout.regions.some(r=>o.x>r.bx*300+63&&o.x<(r.bx+r.w)*300&&o.y>r.by*300+63&&o.y<(r.by+r.h)*300))}}assert.equal(moved.size,cars.length)}
})
test('cones form fixed curb-aligned rows of five, including after respawn',()=>{
 const s=E.make(19,{ai_count:0});s.holes=[];const cones=s.objects.filter(o=>o.type===1);assert.ok(cones.length>0);assert.equal(cones.length%5,0);for(let i=0;i<cones.length;i+=5)for(let n=0;n<5;n++){assert.equal(cones[i+n].y,cones[i].y);assert.equal(cones[i+n].x,cones[i].x+n*25);assert.equal(cones[i+n].y%300,72)}cones.forEach(o=>o.ready=1);E.step(s);cones.forEach(o=>{assert.equal(o.x,o.homeX);assert.equal(o.y,o.homeY)})
})
test('opponents gain only 75 percent of object growth mass',()=>{
 const masses=[];for(const id of [0,1]){const s=E.make(5,{ai_count:1});s.holes=s.holes.filter(h=>h.id===id);const h=s.holes[0];h.x=h.y=2400;s.objects=[{id:0,type:0,x:2400,y:2400,homeX:2400,homeY:2400,ready:0}];E.step(s);masses.push(h.mass);assert.equal(h.score,4)}assert.deepEqual(masses,[7,5])
})
test('previous city-2 verifier still reproduces its archived engine',()=>{
 const old=require('../static/js/engine-city-2.js'),cp=require('node:child_process'),payload={version:old.VERSION,map:old.MAP,seed:22,config,inputs:[]};const result=cp.spawnSync(process.execPath,['verify.cjs'],{input:JSON.stringify(payload),encoding:'utf8'});assert.equal(result.status,0);assert.deepEqual(JSON.parse(result.stdout),old.replay(payload.seed,config,[]))
})

test('released browser engine is identical to the current server engine',()=>{
 const released=require('../static/js/engine-city-4.js');for(const seed of [1,42,999])assert.deepEqual(released.replay(seed,config,[[0,100,0],[12,0,100]]),E.replay(seed,config,[[0,100,0],[12,0,100]]))
})
