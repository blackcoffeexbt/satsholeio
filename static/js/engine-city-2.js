/* Versioned simulation. Integer positions, ordered events, xorshift32 RNG.
 * The exact same file is loaded in browsers and the server verifier. */
;(function (root) {
  'use strict'
  const VERSION = 'city-2', MAP = 'bitcoin-borough-2', TPS = 20
  const C = {world: 4800, startRadius: 22, speed: 12, growth: 5,
    eatRatio: 140, respawnTicks: 60, huntScore: 30, huntMass: 30}
  const TYPES = [
    ['rubbish', 5, 20, 4, 7, 140], ['cone', 8, 20, 6, 10, 180],
    ['bird', 7, 20, 8, 12, 160], ['person', 10, 26, 14, 20, 220],
    ['bitcoin', 10, 26, 22, 24, 260], ['bin', 13, 32, 22, 32, 260],
    ['bench', 22, 42, 40, 60, 320], ['tree', 26, 48, 55, 80, 340],
    ['bicycle', 20, 40, 35, 50, 300], ['car', 36, 66, 95, 140, 400],
    ['van', 46, 85, 150, 230, 460], ['kiosk', 60, 110, 250, 360, 520],
    ['house', 86, 148, 450, 650, 640], ['tower', 120, 200, 850, 1100, 800]
  ].map(([name,size,minRadius,score,mass,respawn]) => ({name,size,minRadius,score,mass,respawn,shape:'circle'}))
  class RNG {
    constructor(seed) { this.s = seed >>> 0 || 0x9e3779b9 }
    next() { let x=this.s; x^=x<<13; x^=x>>>17; x^=x<<5; return this.s=x>>>0 }
    int(n) { return this.next()%n }
  }
  function isqrt(n) { let x=Math.floor(Math.sqrt(n)); while((x+1)*(x+1)<=n)x++; while(x*x>n)x--; return x }
  const dist = (a,b) => (a.x-b.x)**2+(a.y-b.y)**2
  const radius = mass => C.startRadius + isqrt(mass*C.growth)
  function direction(dx,dy) { const d=Math.max(1,Math.abs(dx),Math.abs(dy)); return [Math.trunc(dx*100/d),Math.trunc(dy*100/d)] }
  // Block pavement surrounds the inset lawn/building area; roads occupy 0..62.
  const PAVEMENT_TYPES=new Set([1,3,5,6,7,8])
  function pavementPosition(x,y,type) {
    if(!PAVEMENT_TYPES.has(type))return [x,y]
    const margin=TYPES[type].size, bx=Math.floor(x/300)*300, by=Math.floor(y/300)*300
    const clamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v))
    const lx=x-bx,ly=y-by, alongX=clamp(lx,63+margin,299-margin),alongY=clamp(ly,63+margin,299-margin)
    const candidates=[[clamp(lx,63+margin,120-margin),alongY],[clamp(lx,244+margin,299-margin),alongY],
      [alongX,clamp(ly,63+margin,120-margin)],[alongX,clamp(ly,244+margin,299-margin)]]
    candidates.sort((a,b)=>((a[0]-lx)**2+(a[1]-ly)**2)-((b[0]-lx)**2+(b[1]-ly)**2))
    return [bx+candidates[0][0],by+candidates[0][1]]
  }
  function growthProgress(mass) {
    const level=Math.floor(isqrt(mass*C.growth)/25)
    const start=Math.ceil((level*25)**2/C.growth),end=Math.ceil(((level+1)*25)**2/C.growth)
    return {size:level+1,fraction:(mass-start)/(end-start)}
  }
  function make(seed, config={}) {
    config={duration:120,ai_count:8,death_penalty:20,...config}
    if(!Number.isInteger(config.duration)||config.duration<1||config.duration>300||!Number.isInteger(config.ai_count)||config.ai_count<0||config.ai_count>16||!Number.isInteger(config.death_penalty)||config.death_penalty<0||config.death_penalty>100)throw Error("Invalid configuration")
    const rng=new RNG(seed), objects=[]
    // Regular city blocks with parks, commercial core, and busy streets.
    for(let i=0;i<1350;i++) {
      let x=60+rng.int(4680), y=60+rng.int(4680), type=rng.int(9)
      if(i<240) { x=120+(i%16)*300+rng.int(80); y=130+Math.floor(i/16)*300+rng.int(80); type=(x>1500&&x<3300&&y>1500&&y<3300)?13:12 }
      else if(i<380) type=9+rng.int(3)
      else if(i<650) { x=40+rng.int(4720); y=300*Math.floor(y/300)+40+rng.int(45); type=rng.int(7) }
      ;[x,y]=pavementPosition(x,y,type)
      objects.push({id:i,type,x,y,homeX:x,homeY:y,ready:0,variant:rng.int(4)})
    }
    // A predictable, plentiful starting plaza for learning the growth loop.
    for(let i=0;i<80;i++) {const type=i%3,[x,y]=pavementPosition(2100+rng.int(600),2100+rng.int(600),type);objects.push({id:objects.length,type,x,y,homeX:x,homeY:y,ready:0,variant:0})}
    const holes=[]
    for(let i=0;i<=config.ai_count;i++) holes.push({id:i,x:i?100+rng.int(4600):2400,y:i?100+rng.int(4600):2400,mass:0,score:0,radius:C.startRadius,deadUntil:0,personality:(i-1)%4,target:null,deaths:0,mx:0,my:0})
    if(holes.length===0) holes.push({id:0,x:2400,y:2400,mass:0,score:0,radius:22,deadUntil:0,personality:0,deaths:0,mx:0,my:0})
    return {seed,config:{duration:120,ai_count:8,death_penalty:20,...config},rng,objects,holes,tick:0}
  }
  function grid(s) {
    const cells=new Map()
    for(const o of s.objects) { if(o.ready>s.tick)continue; const key=Math.floor(o.x/200)+","+Math.floor(o.y/200); if(!cells.has(key))cells.set(key,[]);cells.get(key).push(o) }
    return cells
  }
  function nearby(cells,h,range) {
    const out=[];for(let x=Math.floor((h.x-range)/200);x<=Math.floor((h.x+range)/200);x++)for(let y=Math.floor((h.y-range)/200);y<=Math.floor((h.y+range)/200);y++)out.push(...(cells.get(x+","+y)||[])); return out.sort((a,b)=>a.id-b.id)
  }
  function ai(s,h,cells) {
    const threats=s.holes.filter(o=>o.id!==h.id&&!o.deadUntil&&o.radius*100>=h.radius*C.eatRatio&&dist(o,h)<(o.radius+240)**2)
    if(threats.length&&h.personality!==3) { const t=threats.sort((a,b)=>dist(a,h)-dist(b,h)||a.id-b.id)[0]; return direction(h.x-t.x,h.y-t.y) }
    let best=null, value=-1
    if(h.personality!==0) for(const o of s.holes) {
      if(o.id===h.id||o.deadUntil||h.radius*100<o.radius*C.eatRatio)continue
      const d=dist(h,o), v=(h.personality===1?12000:3500)/(1+Math.floor(d/1000))
      if(d<900**2&&v>value) { value=v; best=o }
    }
    for(const o of nearby(cells,h,900)) {
      if(o.ready>s.tick||TYPES[o.type].minRadius>h.radius)continue
      const d=dist(h,o), v=TYPES[o.type].score*60/(1+Math.floor(d/200))
      if(v>value) { value=v; best=o }
    }
    if(best) return direction(best.x-h.x,best.y-h.y)
    return direction(2400-h.x,2400-h.y)
  }
  function step(s, input=[0,0]) {
    if(s.tick>=s.config.duration*TPS)return
    s.tick++
    for(const o of s.objects) if(o.ready&&o.ready<=s.tick) {
      if(s.holes.some(h=>!h.deadUntil&&dist(h,o)<(h.radius+TYPES[o.type].size+72)**2)){o.ready=s.tick+20;continue}
      o.ready=0; o.x=Math.max(20,Math.min(4780,o.homeX+s.rng.int(101)-50)); o.y=Math.max(20,Math.min(4780,o.homeY+s.rng.int(101)-50)); o.variant=s.rng.int(4)
      ;[o.x,o.y]=pavementPosition(o.x,o.y,o.type)
    }
    const cells=grid(s)
    for(const h of s.holes) {
      if(h.deadUntil) { if(s.tick<h.deadUntil)continue; h.deadUntil=0; h.protectedUntil=s.tick+60; h.mass=0; h.radius=C.startRadius; h.x=100+s.rng.int(4600); h.y=100+s.rng.int(4600) }
      if(h.id===0) { h.mx=input[0];h.my=input[1] }
      else if(s.tick%10===1) [h.mx,h.my]=ai(s,h,cells)
      const d=Math.max(100,isqrt(h.mx*h.mx+h.my*h.my))
      h.x=Math.max(h.radius,Math.min(C.world-h.radius,h.x+Math.trunc(h.mx*C.speed/d)))
      h.y=Math.max(h.radius,Math.min(C.world-h.radius,h.y+Math.trunc(h.my*C.speed/d)))
    }
    // Stable IDs resolve ties; no hidden AI bonuses.
    for(const h of s.holes) {
      if(h.deadUntil)continue
      for(const o of nearby(cells,h,h.radius)) {
        const t=TYPES[o.type]
        if(o.ready>s.tick||h.radius<t.minRadius||dist(h,o)>(h.radius-t.size/2)**2)continue
        h.score+=t.score; h.mass+=t.mass; h.radius=radius(h.mass)
        o.ready=s.tick+t.respawn+s.rng.int(80)
      }
      for(const victim of s.holes) {
        if(victim.id===h.id||victim.deadUntil||(victim.protectedUntil||0)>s.tick||h.radius*100<victim.radius*C.eatRatio||dist(h,victim)>(h.radius-victim.radius/2)**2)continue
        h.score+=C.huntScore+Math.floor(victim.mass/8); h.mass+=C.huntMass+Math.floor(victim.mass/6); h.radius=radius(h.mass)
        victim.score=Math.floor(victim.score*(100-s.config.death_penalty)/100)
        victim.mass=0; victim.radius=C.startRadius; victim.deadUntil=s.tick+C.respawnTicks; victim.deaths++
      }
    }
  }
  function replay(seed,config,inputs) {
    make(seed,config) // Validate bounded configuration before allocating replay work.
    if(!Array.isArray(inputs)||inputs.length>config.duration*TPS)throw Error('Invalid input count')
    let prev=-1
    for(const row of inputs) {
      if(!Array.isArray(row)||row.length!==3||!row.every(Number.isInteger)||row[0]<=prev||row[0]<0||row[0]>=config.duration*TPS||Math.abs(row[1])>100||Math.abs(row[2])>100)throw Error('Invalid input stream')
      prev=row[0]
    }
    const s=make(seed,config); let cursor=0, move=[0,0]
    for(let t=0;t<config.duration*TPS;t++) { if(cursor<inputs.length&&inputs[cursor][0]===t)move=inputs[cursor++].slice(1); step(s,move) }
    const p=s.holes[0]
    return {score:p.score,mass:p.mass,radius:p.radius,x:p.x,y:p.y,deaths:p.deaths,ticks:s.tick}
  }
  const engine={VERSION,MAP,TPS,C,TYPES,RNG,make,step,replay,pavementPosition,growthProgress}
  if(typeof module!=='undefined')module.exports=engine
  else root.SatsHoleEngine=engine
})(typeof globalThis!=='undefined'?globalThis:this)
