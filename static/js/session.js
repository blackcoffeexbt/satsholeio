const API='/satshole/api/v1/game'
export async function request(path,body,method=body===undefined?'GET':'POST'){
 const response=await fetch(API+path,{method,credentials:'same-origin',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)})
 const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Request could not be completed.');return data
}
export class GameSession {
 constructor(){this.info=null;this.run=null;this.token=null;this.poll=null}
 async init(){this.info=await request('/session',{});return this.info}
 async prepare(free){const existing=this.info?.runs.find(r=>r.status==='READY'||r.status==='WAITING_PAYMENT');this.run=existing||await request('/runs',{free});return this.run}
 async start(){const data=await request('/runs/'+this.run.id+'/start',{});this.token=data.run_token;return data}
 async status(){this.run=await request('/runs/'+this.run.id);return this.run}
 async finish(inputs){return await request('/runs/'+this.run.id+'/finish',{run_token:this.token,inputs})}
}
