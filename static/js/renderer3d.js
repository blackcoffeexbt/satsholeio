import * as THREE from '../vendor/three.module.js'

// Presentation only: simulation coordinates (x,y) become world coordinates (x,z).
export class CityRenderer {
  constructor(canvas, engine, colors, names) {
    this.engine=engine;this.colors=colors;this.names=names
    this.renderer=new THREE.WebGLRenderer({canvas,antialias:true})
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.5))
    this.renderer.setClearColor('#abc8d2');this.renderer.outputColorSpace=THREE.SRGBColorSpace
    this.scene=new THREE.Scene();this.scene.fog=new THREE.Fog('#abc8d2',2200,6500)
    this.camera=new THREE.PerspectiveCamera(45,1,5,9000)
    this.scene.add(new THREE.HemisphereLight(0xeaf6ff,0x6f785f,2.2))
    const sun=new THREE.DirectionalLight(0xffefd3,2.5);sun.position.set(-900,1600,600);this.scene.add(sun)
    this.box=new THREE.BoxGeometry(1,1,1);this.sphere=new THREE.IcosahedronGeometry(1,0)
    this.cylinder=new THREE.CylinderGeometry(1,1,1,10);this.cone=new THREE.ConeGeometry(1,1,5)
    this.materials=new Map();this.holeUniform={value:Array.from({length:17},()=>new THREE.Vector3(-10000,-10000,0))}
    this.dynamic=new THREE.Group();this.scene.add(this.dynamic);this.objects=[];this.holes=[]
    this.previous=[];this.target=new THREE.Vector3();this.frustum=new THREE.Frustum();this.projection=new THREE.Matrix4();this.bounds=new THREE.Sphere();
    this.follow=new THREE.Vector3(2400,0,2400);this.distance=420
    this.batches=new Map();this.ground=new THREE.Group();this.scene.add(this.ground);this.popups=[];this.previousObjects=[]
    this.raycaster=new THREE.Raycaster();this.plane=new THREE.Plane(new THREE.Vector3(0,1,0),0)
    this.resize()
  }
  material(color,ground=false){const key=color+ground;if(this.materials.has(key))return this.materials.get(key)
    const m=new THREE.MeshStandardMaterial({color,roughness:.85,transparent:ground==='building',depthWrite:ground!=='building'})
    if(ground)m.onBeforeCompile=shader=>{
      shader.uniforms.holes=this.holeUniform
      shader.vertexShader='varying vec3 cityPosition;\n'+shader.vertexShader.replace('#include <worldpos_vertex>','#include <worldpos_vertex>\ncityPosition=(modelMatrix * vec4(transformed,1.0)).xyz;\n#ifdef USE_INSTANCING\ncityPosition=(modelMatrix * instanceMatrix * vec4(transformed,1.0)).xyz;\n#endif')
      shader.fragmentShader='uniform vec3 holes[17]; varying vec3 cityPosition;\n'+shader.fragmentShader.replace('#include <clipping_planes_fragment>',ground==='building'?'#include <clipping_planes_fragment>\nif(distance(cityPosition.xz-vec2(0.3158,0.8421)*cityPosition.y,holes[0].xy)<holes[0].z+70.0)diffuseColor.a=0.16;':'#include <clipping_planes_fragment>\nfor(int i=0;i<17;i++){if(distance(cityPosition.xz,holes[i].xy)<holes[i].z)discard;}')
    }
    this.materials.set(key,m);return m
  }
  part(group,geometry,color,x,y,z,sx,sy,sz,ground=false){const mesh=new THREE.Mesh(geometry,this.material(color,ground));mesh.position.set(x,y,z);mesh.scale.set(sx,sy,sz);group.add(mesh);return mesh}
  batch(color,x,y,z,sx,sy,sz,ground=true){const key=color+ground;if(!this.batches.has(key))this.batches.set(key,{color,ground,rows:[]});this.batches.get(key).rows.push([x,y,z,sx,sy,sz])}
  flushBatches(){const dummy=new THREE.Object3D();for(const {color,ground,rows} of this.batches.values()){const mesh=new THREE.InstancedMesh(this.box,this.material(color,ground),rows.length);rows.forEach((r,i)=>{dummy.position.set(...r.slice(0,3));dummy.scale.set(...r.slice(3));dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix)});this.ground.add(mesh)}this.batches.clear()}
  buildGround(layout={regions:[]}){for(const mesh of this.ground.children)if(mesh.isInstancedMesh)mesh.dispose();this.ground.clear();this.batch('#46505c',2400,-4,2400,4800,8,4800)
    for(let x=0;x<4800;x+=300)for(let z=0;z<4800;z+=300){
      this.batch('#afb9bb',x+181,0,z+181,236,5,236)
      const park=(x/300+z/300)%7===0
      this.batch(park?'#7ba86b':'#c7ceca',x+182,3,z+182,124,3,124)
      for(let n=0;n<6;n++){this.batch('#f6f1da',x+10+n*9,1,z+80,5,1,28);this.batch('#f6f1da',x+80,1,z+10+n*9,28,1,5)}
      for(let n=90;n<290;n+=55){this.batch('#d4d9d6',x+31,1,z+n,3,1,23);this.batch('#d4d9d6',x+n,1,z+31,23,1,3)}
      for(let n=85;n<295;n+=35){this.batch('#96a4a6',x+n,3,z+71,1,1,224);this.batch('#96a4a6',x+71,3,z+n,224,1,1)}
    }
    for(const r of layout.regions){const x=r.bx*300+63,z=r.by*300+63,w=r.w*300-63,d=r.h*300-63,cx=x+w/2,cz=z+d/2
      this.batch('#b9c3bc',cx,5,cz,w,6,d)
      if(r.kind==='park'||r.kind==='pond'){
        this.batch('#78a968',cx,9,cz,w-120,3,d-120)
        // Offset paths and a long pond replace roads through these larger districts.
        this.batch('#e2d6b4',cx-70,12,cz,23,2,d-45);this.batch('#e2d6b4',cx,12,cz+110,w-45,2,22)
        if(r.kind==='pond') {this.part(this.ground,this.cylinder,'#c9c3a0',cx+60,13,cz-45,w*.29,3,d*.24,true);this.part(this.ground,this.cylinder,'#5dacc3',cx+60,15,cz-45,w*.275,2,d*.225,true)}
      }else if(r.kind==='parking'){
        this.batch('#65727b',cx,10,cz,w-35,3,d-35)
        for(let row=0;row<2;row++)for(let n=0;n<9;n++)this.batch('#eae8ce',r.bx*300+88+n*53,13,r.by*300+155+row*160,2,1,95)
      }else if(r.kind==='neighborhood'){this.batch('#d1cbbb',cx,10,cz,w-25,3,d-25);this.batch('#a7b993',cx,12,cz,w*.45,2,25);this.batch('#e5dcc8',cx-80,12,cz,18,2,d-45)}else {this.batch('#ccd0c3',cx,10,cz,w-30,3,d-30);this.batch('#85a774',cx,12,z+40,w-60,2,28)}
    }
    this.batch('#628c9b',-75,-6,2400,150,8,5100);this.batch('#628c9b',4875,-6,2400,150,8,5100)
  }
  objectModel(o){const g=new THREE.Group(),t=this.engine.TYPES[o.type],r=t.size,v=o.variant
    const box=(c,x,y,z,sx,sy,sz)=>this.part(g,this.box,c,x,y,z,sx,sy,sz,o.type>=11?'building':false)
    if(o.type>=11){const height=o.height||(o.type===13?135+v*55:o.type===12?70+v*25:45)
      const c=['#d29b79','#81b4b7','#d8c298','#bd8f9a'][v]
      box(c,0,height/2,0,r*(o.type===14?1.35:1.6),height,r*1.5);box('#596d79',0,height+3,0,r*1.7,6,r*1.6)
      box('#b8c8cd',r*.25,height+10,0,r*.35,14,r*.3)
      for(let y=18;y<height-5;y+=25){box('#416e8b',0,y,r*.755,r*1.35,13,1);box('#3e718b',r*.805,y,0,1,13,r*1.3);box('#4b819e',-r*.805,y,0,1,13,r*1.3)}
      box('#38596c',0,12,r*.76,18,24,2)
    }else if(o.type===7){box('#8b7055',0,16,0,6,32,6);this.part(g,this.sphere,'#6eaa59',0,40,0,r,25,r);this.part(g,this.sphere,'#86bb62',-9,49,3,r*.6,17,r*.7)
    }else if(o.type===9||o.type===10){const c=['#eead42','#e77c68','#67a8ba','#ece6cc'][v];box(c,0,10,0,r*1.8,14,r*.6);box('#436c86',-r*.15,22,0,r*.85,14,r*.55);box(c,-r*.15,30,0,r*.9,3,r*.8);for(const x of [-r*.6,r*.6])for(const z of [-r*.45,r*.45])box('#283944',x,6,z,12,12,5);box('#fff0c3',r*.91,12,0,2,5,r*.6)
    }else if(o.type===3){box(['#e8856e','#548bad','#aa80ad','#e0b652'][v],0,16,0,9,16,7);this.part(g,this.sphere,'#edc49e',0,29,0,5,6,5);box('#3c536a',-3,5,0,3,12,4);box('#3c536a',3,5,0,3,12,4)
    }else if(o.type===4){const coin=this.part(g,this.cylinder,'#ffbe43',0,16,0,10,3,10);coin.rotation.z=Math.PI/2;g.userData.coin=coin
      const c=document.createElement('canvas');c.width=c.height=64;const ctx=c.getContext('2d');ctx.fillStyle='#9d6627';ctx.font='bold 52px sans-serif';ctx.textAlign='center';ctx.fillText('₿',32,51);const m=new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c)}),s=new THREE.Sprite(m);s.position.y=16;s.scale.set(17,17,1);g.add(s)
    }else if(o.type===1){this.part(g,this.cone,'#ef9860',0,9,0,4,18,4);box('#f4ead4',0,1,0,8,2,8)
    }else if(o.type===6){box('#a58261',0,9,0,42,5,13);box('#a58261',0,18,-6,42,16,3);box('#4f6468',-15,4,0,3,8,10);box('#4f6468',15,4,0,3,8,10)
    }else if(o.type===5){this.part(g,this.cylinder,'#587b76',0,12,0,10,24,10);box('#8eb6a4',0,25,0,22,3,22)
    }else if(o.type===2){box('#f6eee0',-5,9,0,9,2,4);box('#f6eee0',5,9,0,9,2,4)
    }else if(o.type===8){box('#6788a5',0,12,0,30,3,3);for(const x of [-12,12]){const wheel=this.part(g,this.cylinder,'#34464e',x,8,0,8,2,8);wheel.rotation.x=Math.PI/2}}
    else box('#ded4ae',0,3,0,9,6,8)
    g.position.set(o.x,0,o.y);g.userData={...g.userData,ready:o.ready,fall:0,angle:o.traffic?(o.axis?Math.PI/2:0)+(o.dir<0?Math.PI:0):(o.angle||0),height:o.height||(o.type>=11?180:45)};g.rotation.y=g.userData.angle;return g
  }
  reset(state){this.buildGround(state.layout);this.flushBatches();this.clearPopups();for(const g of [...this.objects,...this.holes]){this.dynamic.remove(g);g.traverse(n=>{if(n.isSprite){n.material.map.dispose();n.material.dispose()}})}this.objects=state.objects.map(o=>{const g=this.objectModel(o);this.dynamic.add(g);return g})
    this.holes=state.holes.map(h=>{const g=new THREE.Group()
      const rim=new THREE.Mesh(new THREE.TorusGeometry(1,.045,6,48),new THREE.MeshBasicMaterial({color:this.colors[h.id%this.colors.length]}));rim.rotation.x=Math.PI/2;rim.position.y=.025;g.add(rim)
      if(h.id===0){
        const material=new THREE.MeshBasicMaterial({color:this.colors[0],side:THREE.DoubleSide})
        const progress={value:0}
        material.onBeforeCompile=shader=>{shader.uniforms.progress=progress;shader.vertexShader='varying vec2 arcPosition;\n'+shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\narcPosition=position.xy;');shader.fragmentShader='uniform float progress; varying vec2 arcPosition;\n'+shader.fragmentShader.replace('#include <clipping_planes_fragment>','#include <clipping_planes_fragment>\nfloat angle=mod(atan(arcPosition.x,arcPosition.y)+6.2831853,6.2831853);if(progress<=0.0||angle>progress*6.2831853)discard;')}
        const arc=new THREE.Mesh(new THREE.RingGeometry(1.13,1.19,128),material);arc.rotation.x=-Math.PI/2;arc.position.y=.04;g.add(arc);g.userData.progress=progress
      }
      const wall=new THREE.Mesh(new THREE.CylinderGeometry(.99,.58,1,40,1,true),new THREE.MeshBasicMaterial({color:'#19242d',side:THREE.BackSide}));wall.position.y=-.49;g.add(wall)
      const floor=new THREE.Mesh(new THREE.CircleGeometry(.6,40),new THREE.MeshBasicMaterial({color:'#05080d',side:THREE.DoubleSide}));floor.rotation.x=-Math.PI/2;floor.position.y=-.98;g.add(floor)
      const c=document.createElement('canvas');c.width=256;c.height=64;const ctx=c.getContext('2d');ctx.font='bold 32px sans-serif';ctx.textAlign='center';ctx.fillStyle=this.colors[h.id%this.colors.length];ctx.fillText(this.names[h.id%this.names.length],128,43);const label=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c),depthTest:false}));label.scale.set(100,25,1);g.add(label);g.userData.label=label;this.dynamic.add(g);return g})
    this.follow.set(state.holes[0].x,0,state.holes[0].y);this.captureTick(state)
  }
  resize(){this.renderer.setSize(innerWidth,innerHeight,false);this.camera.aspect=innerWidth/innerHeight;this.camera.updateProjectionMatrix()}
  movement(dx,dy){const forward=new THREE.Vector3();this.camera.getWorldDirection(forward);forward.y=0;forward.normalize();const right=new THREE.Vector3().crossVectors(forward,new THREE.Vector3(0,1,0));const v=right.multiplyScalar(dx).add(forward.multiplyScalar(-dy));return [Math.round(v.x),Math.round(v.z)]}
  mouseMovement(x,y,player){this.raycaster.setFromCamera(new THREE.Vector2(x/innerWidth*2-1,1-y/innerHeight*2),this.camera);const p=new THREE.Vector3();if(!this.raycaster.ray.intersectPlane(this.plane,p))return [0,0];const dx=p.x-player.x,dy=p.z-player.y,d=Math.max(35,Math.abs(dx),Math.abs(dy));return [Math.trunc(dx*100/d),Math.trunc(dy*100/d)]}
  captureTick(state){this.previousObjects=state.objects.map(o=>({x:o.x,y:o.y,ready:o.ready}));state.holes.forEach((h,i)=>{const p=this.previous[i] ||= {};p.x=h.x;p.y=h.y;p.radius=h.radius;p.mass=h.mass;p.deadUntil=h.deadUntil})}
  pose(h,i,alpha){const p=this.previous[i];if(!p||p.deadUntil!==h.deadUntil)return h;return {mass:p.mass+(h.mass-p.mass)*alpha,x:p.x+(h.x-p.x)*alpha,y:p.y+(h.y-p.y)*alpha,radius:p.radius+(h.radius-p.radius)*alpha}}
  clearPopups(){for(const p of this.popups){this.dynamic.remove(p.sprite);p.sprite.material.map.dispose();p.sprite.material.dispose()}this.popups=[]}
  points(value,hole){if(this.popups.length>=32){const old=this.popups.shift();this.dynamic.remove(old.sprite);old.sprite.material.map.dispose();old.sprite.material.dispose()}
    const c=document.createElement('canvas');c.width=256;c.height=96;const ctx=c.getContext('2d');ctx.font='bold 54px sans-serif';ctx.textAlign='center';ctx.lineWidth=7;ctx.strokeStyle='#283742';ctx.fillStyle='#fff3a7';ctx.strokeText('+'+value,128,65);ctx.fillText('+'+value,128,65)
    const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c),depthTest:false,transparent:true}));sprite.position.set(hole.x,50,hole.y);sprite.scale.set(90,34,1);this.dynamic.add(sprite);this.popups.push({sprite,age:0})
  }
  draw(state,alpha=1,dt=1/60){if(this.objects.length!==state.objects.length)this.reset(state)
    const player=this.pose(state.holes[0],0,alpha)
    this.target.set(player.x,0,player.y)
    this.follow.lerp(this.target,1-Math.exp(-6.3*dt));this.distance+=(Math.max(360,360+player.radius*3)-this.distance)*(1-Math.exp(-2.45*dt))
    this.camera.position.set(this.follow.x+this.distance*.3,this.distance*.95,this.follow.z+this.distance*.8);this.camera.lookAt(this.follow)
    this.camera.updateMatrixWorld();this.projection.multiplyMatrices(this.camera.projectionMatrix,this.camera.matrixWorldInverse);this.frustum.setFromProjectionMatrix(this.projection)
    this.holeUniform.value.forEach(v=>v.set(-10000,-10000,0))
    state.holes.forEach((h,i)=>{const pose=this.pose(h,i,alpha),r=pose.radius,g=this.holes[i];g.visible=!h.deadUntil;if(g.userData.progress){const current=this.engine.growthProgress(h.mass),previous=this.engine.growthProgress(this.previous[i]?.mass??h.mass);g.userData.progress.value=current.size===previous.size?previous.fraction+(current.fraction-previous.fraction)*alpha:current.fraction}g.position.set(pose.x,0,pose.y);g.scale.set(r,r*1.8,r);g.userData.label.position.set(0,.35,-1.3);g.userData.label.scale.set(100/r,25/(r*1.8),1);if(!h.deadUntil)this.holeUniform.value[i].set(pose.x,pose.y,r)})
    state.objects.forEach((o,i)=>{const g=this.objects[i],data=g.userData,eaten=o.ready>state.tick;if(o.traffic)data.angle=(o.axis?Math.PI/2:0)+(o.dir<0?Math.PI:0)
      if(eaten&&!data.ready){const h=state.holes[o.eatenBy??0];data.fall=0;data.fallX=g.position.x;data.fallZ=g.position.z;data.towardX=h.x;data.towardZ=h.y;data.dropRadius=h.radius;if(o.eatenBy===0)this.points(this.engine.TYPES[o.type].score,h)}
      if(!eaten){
        const p=this.previousObjects[i],smooth=o.traffic&&p&&!p.ready&&Math.abs(p.x-o.x)<100&&Math.abs(p.y-o.y)<100
        g.position.set(smooth?p.x+(o.x-p.x)*alpha:o.x,0,smooth?p.y+(o.y-p.y)*alpha:o.y);g.scale.setScalar(1);g.rotation.set(0,data.angle,0)
        // Begin leaning as support disappears under the near edge. The lean axis
        // points toward the hole rather than applying the same rotation to everything.
        if(o.type>=11){const h=state.holes.filter(h=>!h.deadUntil&&h.radius>=this.engine.TYPES[o.type].minRadius).sort((a,b)=>(a.x-o.x)**2+(a.y-o.y)**2-((b.x-o.x)**2+(b.y-o.y)**2))[0]
          if(h){const dx=h.x-o.x,dz=h.y-o.y,d=Math.hypot(dx,dz),overlap=Math.max(0,Math.min(1,(h.radius+this.engine.TYPES[o.type].size*.65-d)/(this.engine.TYPES[o.type].size*1.3)));g.rotation.x=dz/Math.max(1,d)*overlap*.65;g.rotation.z=-dx/Math.max(1,d)*overlap*.65}
        }
        const height=data.height;this.bounds.center.set(o.x,height/2,o.y);this.bounds.radius=height+this.engine.TYPES[o.type].size;g.visible=this.frustum.intersectsSphere(this.bounds)
        if(g.visible&&data.coin)data.coin.rotation.y=(state.tick-1+alpha)*.15
      }else{
        data.fall+=dt;const t=data.fall,dx=data.towardX-data.fallX,dz=data.towardZ-data.fallZ,d=Math.max(1,Math.hypot(dx,dz)),lean=Math.min(1.25,t*1.8),pull=1-Math.exp(-t*3)
        g.position.set(data.fallX+dx*pull,-.5*420*t*t,data.fallZ+dz*pull);g.rotation.set(dz/d*lean,data.angle,-dx/d*lean);g.visible=t<1.8
        // Keep full object dimensions while gravity carries it beneath the surface.
      }
      data.ready=eaten
    })
    for(let i=this.popups.length-1;i>=0;i--){const p=this.popups[i];p.age+=dt;p.sprite.position.y+=65*dt;p.sprite.material.opacity=Math.max(0,1-p.age/1.3);if(p.age>1.3){this.dynamic.remove(p.sprite);p.sprite.material.map.dispose();p.sprite.material.dispose();this.popups.splice(i,1)}}
    this.renderer.render(this.scene,this.camera)
  }
}
