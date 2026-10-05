/* Versioned simulation. Integer positions, ordered events, xorshift32 RNG.
 * The exact same file is loaded in browsers and the server verifier. */
;(function (root) {
  'use strict'
  const VERSION = 'city-3', MAP = 'bitcoin-borough-3', TPS = 20
  const C = {world: 4800, startRadius: 22, speed: 12, growth: 5,
    eatRatio: 140, respawnTicks: 60, huntScore: 30, huntMass: 30}
  const TYPES = [
    ['rubbish', 5, 20, 4, 7, 140], ['cone', 4, 20, 6, 10, 180],
    ['bird', 7, 20, 8, 12, 160], ['person', 10, 26, 14, 20, 220],
    ['bitcoin', 10, 26, 120, 24, 900], ['bin', 13, 32, 22, 32, 260],
    ['bench', 22, 42, 40, 60, 320], ['tree', 26, 48, 55, 80, 340],
    ['bicycle', 20, 40, 35, 50, 300], ['car', 36, 66, 95, 140, 400],
    ['van', 46, 85, 150, 230, 460], ['kiosk', 60, 110, 250, 360, 520],
    ['house', 86, 148, 450, 650, 640], ['tower', 100, 170, 850, 1100, 800],
    ['terrace', 38, 72, 180, 260, 640], ['landmark', 180, 300, 1800, 2100, 1000],
    ['megablock', 270, 430, 3200, 3300, 1200]
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
  function makeLayout(seed){
    const rng=new RNG(seed^0x51f15e),regions=[]
    for(const kind of ['park','park','pond','campus','parking']) {
      const w=kind==='campus'?3:2,h=2
      for(let tries=0;tries<100;tries++){
        const bx=1+rng.int(13-w),by=1+rng.int(13-h)
        if(regions.some(r=>bx<r.bx+r.w+1&&bx+w+1>r.bx&&by<r.by+r.h+1&&by+h+1>r.by))continue
        regions.push({kind,bx,by,w,h});break
      }
    }
    return {regions}
  }
  function make(seed, config={}) {
    config={duration:120,ai_count:8,death_penalty:20,...config}
    if(!Number.isInteger(config.duration)||config.duration<1||config.duration>300||!Number.isInteger(config.ai_count)||config.ai_count<0||config.ai_count>16||!Number.isInteger(config.death_penalty)||config.death_penalty<0||config.death_penalty>100)throw Error("Invalid configuration")
    const rng=new RNG(seed), objects=[]
    const layout=makeLayout(seed)
    const add=(type,x,y,extra={})=>objects.push({id:objects.length,type,x,y,homeX:x,homeY:y,ready:0,variant:rng.int(4),...extra})
    for(let bx=0;bx<16;bx++)for(let by=0;by<16;by++) {
      if(layout.regions.some(r=>bx>=r.bx&&bx<r.bx+r.w&&by>=r.by&&by<r.by+r.h))continue
      const x=bx*300,y=by*300,style=rng.int(5)
      if(style===0){for(let n=0;n<3;n++)add(14,x+142+n*53,y+175,{angle:0,height:48+rng.int(28)})}
      else if(style<4)add(style===3?13:12,x+170+rng.int(24),y+165+rng.int(30),{angle:(rng.int(3)-1)*.12,height:style===3?150+rng.int(220):55+rng.int(95)})
      else {add(11,x+152,y+159);add(14,x+214,y+217,{height:70})}
      // Construction groups sit parallel to the curb, never scattered into traffic.
      if(rng.int(4)===0)for(let n=0;n<5;n++)add(1,x+94+n*25,y+72,{fixed:true})
    }
    for(const r of layout.regions){
      if(r.kind==='park'||r.kind==='pond')for(let b=0;b<r.h;b++)for(let n=0;n<3;n++){add(7,r.bx*300+94,(r.by+b)*300+140+n*55);add(7,(r.bx+r.w)*300-28,(r.by+b)*300+140+n*55)}
      if(r.kind==='campus'){add(16,r.bx*300+340,r.by*300+330,{height:260+rng.int(140)});add(15,r.bx*300+700,r.by*300+335,{height:190+rng.int(110)})}
      if(r.kind==='parking')for(let row=0;row<2;row++)for(let n=0;n<8;n++)if(rng.int(5)!==0)add(9,r.bx*300+115+n*53,r.by*300+155+row*160,{parked:true,fixed:true,angle:Math.PI/2})
    }
    for(let i=0;i<830;i++){
      let type=[0,0,0,2,3,3,5,6,7,8][rng.int(10)],x=65+rng.int(4660),y=65+rng.int(4660)
      ;[x,y]=pavementPosition(x,y,type);if(layout.regions.some(r=>x>=r.bx*300+63&&x<(r.bx+r.w)*300&&y>=r.by*300+63&&y<(r.by+r.h)*300))continue;add(type,x,y)
    }
    for(let i=0;i<24;i++)add(4,100+rng.int(4600),100+rng.int(4600))
    // Pick uninterrupted road corridors outside merged districts; integer movement
    // is part of replay, while interpolation remains presentation-only.
    for(let i=0;i<100;i++){
      const axis=i%2,lanes=[]
      for(let b=0;b<16;b++)if(!layout.regions.some(r=>b>(axis?r.bx:r.by)&&b<(axis?r.bx+r.w:r.by+r.h)))lanes.push(b)
      const lane=lanes[rng.int(lanes.length)]*300+(i%4<2?16:47),along=rng.int(4800)
      add(i%6===0?10:9,axis?lane:along,axis?along:lane,{traffic:true,axis,lane,speed:3+rng.int(4),dir:i%4<2?1:-1})
    }
    for(let i=0;i<65;i++){const type=0,[x,y]=[2200+rng.int(400),2200+rng.int(400)];add(type,x,y)}
    const holes=[]
    for(let i=0;i<=config.ai_count;i++) holes.push({id:i,x:i?100+rng.int(4600):2400,y:i?100+rng.int(4600):2400,mass:0,score:0,radius:C.startRadius,deadUntil:0,personality:(i-1)%4,target:null,deaths:0,mx:0,my:0})
    if(holes.length===0) holes.push({id:0,x:2400,y:2400,mass:0,score:0,radius:22,deadUntil:0,personality:0,deaths:0,mx:0,my:0})
    return {seed,config:{duration:120,ai_count:8,death_penalty:20,...config},rng,objects,holes,layout,tick:0}
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
      o.ready=0; if(o.fixed||o.type>=11){o.x=o.homeX;o.y=o.homeY;continue} o.x=Math.max(20,Math.min(4780,o.homeX+s.rng.int(101)-50)); o.y=Math.max(20,Math.min(4780,o.homeY+s.rng.int(101)-50)); o.variant=s.rng.int(4)
      ;[o.x,o.y]=pavementPosition(o.x,o.y,o.type)
    }
    for(const o of s.objects)if(o.traffic&&o.ready<=s.tick){
      const key=o.axis?'y':'x';o[key]=(o[key]+o.speed*o.dir+C.world)%C.world;o[o.axis?'x':'y']=o.lane
    }
    const cells=grid(s)
    for(const h of s.holes) {
      if(h.deadUntil) { if(s.tick<h.deadUntil)continue; h.deadUntil=0; h.protectedUntil=s.tick+60; h.mass=0; h.radius=C.startRadius; h.x=100+s.rng.int(4600); h.y=100+s.rng.int(4600) }
      if(h.id===0) { h.mx=input[0];h.my=input[1] }
      else if(s.tick%10===1) [h.mx,h.my]=ai(s,h,cells)
      const d=Math.max(100,isqrt(h.mx*h.mx+h.my*h.my))
      h.x=Math.max(h.radius,Math.min(C.world-h.radius,h.x+Math.trunc(h.mx*(h.id?9:C.speed)/d)))
      h.y=Math.max(h.radius,Math.min(C.world-h.radius,h.y+Math.trunc(h.my*(h.id?9:C.speed)/d)))
    }
    // Opponents use a disclosed 55% growth rate and lower movement speed.
    for(const h of s.holes) {
      if(h.deadUntil)continue
      for(const o of nearby(cells,h,h.radius)) {
        const t=TYPES[o.type]
        if(o.ready>s.tick||h.radius<t.minRadius||dist(h,o)>(h.radius-t.size/2)**2)continue
        h.score+=t.score; h.mass+=h.id?Math.floor(t.mass*.55):t.mass; h.radius=radius(h.mass)
        o.eatenBy=h.id;o.eatenTick=s.tick;o.ready=s.tick+t.respawn+s.rng.int(80)
      }
      for(const victim of s.holes) {
        if(victim.id===h.id||victim.deadUntil||(victim.protectedUntil||0)>s.tick||h.radius*100<victim.radius*C.eatRatio||dist(h,victim)>(h.radius-victim.radius/2)**2)continue
        h.score+=C.huntScore+Math.floor(victim.mass/8); h.mass+=Math.floor((C.huntMass+Math.floor(victim.mass/6))*(h.id?.55:1)); h.radius=radius(h.mass)
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
  const engine={VERSION,MAP,TPS,C,TYPES,RNG,make,step,replay,pavementPosition,growthProgress,makeLayout}
  if(typeof module!=='undefined')module.exports=engine
  else root.SatsHoleEngine=engine
})(typeof globalThis!=='undefined'?globalThis:this)
