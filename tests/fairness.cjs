/* Headless fixed-city baseline. Usage: node tests/fairness.cjs 1000 */
const E=require('../static/js/engine.js')
const count=Number(process.argv[2]||100)
if(!Number.isInteger(count)||count<1||count>10000)throw Error('Use 1–10000 seeds')
const scores=[],deaths=[]
for(let seed=1;seed<=count;seed++){
 const s=E.make(seed,{duration:120,ai_count:8,death_penalty:20})
 // Deterministic simple square-route human baseline, not an optimal player.
 for(let t=0;t<2400;t++){const phase=Math.floor(t/180)%4;E.step(s,[[100,0],[0,100],[-100,0],[0,-100]][phase])}
 scores.push(s.holes[0].score);deaths.push(s.holes[0].deaths)
}
scores.sort((a,b)=>a-b)
console.log(JSON.stringify({seeds:count,min:scores[0],median:scores[Math.floor(count/2)],max:scores[count-1],mean:scores.reduce((a,b)=>a+b)/count,meanDeaths:deaths.reduce((a,b)=>a+b)/count},null,2))
