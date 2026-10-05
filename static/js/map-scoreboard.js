// Current-map presentation only; weekly paid-entry ranking is separate.
export function rankHoles(holes) {
  return [...holes].sort((a,b)=>b.score-a.score||a.id-b.id)
}
export class MapScoreboard {
  constructor(panel,list,colors,names){this.panel=panel;this.list=list;this.colors=colors;this.names=names;this.signature=''}
  reset(playerName){this.playerName=playerName;this.signature='';this.panel.hidden=false}
  update(holes){const ranked=rankHoles(holes),signature=ranked.map(h=>`${h.id}:${h.score}:${!!h.deadUntil}`).join('|');if(signature===this.signature)return;this.signature=signature
    const fragment=document.createDocumentFragment()
    ranked.forEach((h,index)=>{const row=document.createElement('li');row.className=h.id===0?'map-player':'';row.style.setProperty('--hole-color',this.colors[h.id%this.colors.length]);const place=document.createElement('span');place.className='map-place';place.textContent=index===0?'♛':String(index+1);const name=document.createElement('span');name.className='map-name';name.textContent=h.id===0?`YOU · ${this.playerName||'Player'}`:this.names[h.id%this.names.length];if(h.deadUntil)name.textContent+=' · respawning';const score=document.createElement('strong');score.textContent=h.score.toLocaleString();row.append(place,name,score);fragment.append(row)});this.list.replaceChildren(fragment)
  }
}
