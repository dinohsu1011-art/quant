(function(){
  "use strict";
  const DATA=window.QUANT_SECTORS,stage=document.getElementById("stage"),tip=document.getElementById("tip");
  const METRICS={week:{label:"weekly return",short:"Weekly",pct:true},month:{label:"one-month return",short:"1 month",pct:true},ytd:{label:"year-to-date return",short:"YTD",pct:true},ma50:{label:"distance from 50-day average",short:"50-day spread",pct:true}};
  const state={view:"heatmap",metric:"week",range:"1y",cleared:false,focus:null};
  const computed={};
  const monday=date=>{const d=new Date(date+"T00:00:00Z"),day=(d.getUTCDay()+6)%7;d.setUTCDate(d.getUTCDate()-day);return d.toISOString().slice(0,10);};
  const fmt=value=>value==null||!Number.isFinite(value)?"—":`${value>=0?"+":""}${(value*100).toFixed(1)}%`;
  function calculate(close){
    const out={week:[],month:[],ytd:[],ma50:[]};let weekBase=null,weekKey="",year="",yearBase=null,sum=0;
    close.forEach((price,i)=>{
      const wk=monday(DATA.dates[i]);if(wk!==weekKey){weekKey=wk;weekBase=i?close[i-1]:null;}
      const yr=DATA.dates[i].slice(0,4);if(yr!==year){year=yr;yearBase=i?close[i-1]:null;}
      sum+=price;if(i>=50)sum-=close[i-50];
      out.week.push(weekBase?price/weekBase-1:null);
      out.month.push(i>=21?price/close[i-21]-1:null);
      out.ytd.push(yearBase?price/yearBase-1:null);
      out.ma50.push(i>=49?price/(sum/50)-1:null);
    });
    return out;
  }
  if(DATA?.series?.length===11)DATA.series.forEach(row=>computed[row.id]=calculate(row.close));
  const latest=row=>computed[row.id][state.metric].at(-1);
  function color(value,scale){
    if(!Number.isFinite(value))return {bg:"#e7e5e4",ink:"#0c0a09"};
    const t=Math.min(1,Math.abs(value)/scale),target=value>=0?[29,127,196]:[184,72,79],base=[255,255,255];
    const mix=base.map((v,i)=>Math.round(v+(target[i]-v)*(.18+.82*t)));
    return {bg:`rgb(${mix.join(",")})`,ink:t>.55?"#fff":"#0c0a09"};
  }
  function setButtons(){
    document.querySelectorAll("[data-view]").forEach(b=>b.classList.toggle("on",!state.cleared&&b.dataset.view===state.view));
    document.querySelectorAll("[data-metric]").forEach(b=>b.classList.toggle("on",b.dataset.metric===state.metric));
    document.querySelectorAll("[data-range]").forEach(b=>b.classList.toggle("on",b.dataset.range===state.range));
    document.getElementById("rangeGroup").hidden=state.cleared||state.view!=="lines";
  }
  function heatmap(){
    const values=DATA.series.map(latest).filter(Number.isFinite),scale=Math.max(.01,...values.map(Math.abs));
    const grid=document.createElement("div");grid.className="heatmap";
    DATA.series.forEach(row=>{
      const value=latest(row),tone=color(value,scale),button=document.createElement("button");
      button.type="button";button.className="tile"+(state.focus===row.id?" focus":"");button.dataset.sector=row.id;
      button.style.background=tone.bg;button.style.setProperty("--tile-ink",tone.ink);
      button.setAttribute("aria-label",`${row.label}, ${METRICS[state.metric].label} ${fmt(value)}. Open all sector line charts.`);
      button.innerHTML=`<span class="name"></span><span class="ticker"></span><span class="value"></span><span class="date"></span>`;
      button.querySelector(".name").textContent=row.label;button.querySelector(".ticker").textContent=row.ticker;
      button.querySelector(".value").textContent=fmt(value);button.querySelector(".date").textContent=`through ${DATA.as_of}`;
      button.addEventListener("click",()=>{state.focus=row.id;state.view="lines";state.cleared=false;render();});grid.appendChild(button);
    });stage.replaceChildren(grid);
  }
  function lineSvg(row){
    const values=computed[row.id][state.metric],days={"1y":370,"3y":1100,"5y":1900}[state.range],cutoff=new Date(DATA.as_of+"T00:00:00Z");cutoff.setUTCDate(cutoff.getUTCDate()-days);
    let points=DATA.dates.map((date,i)=>({date,value:values[i],i})).filter(p=>p.date>=cutoff.toISOString().slice(0,10)&&Number.isFinite(p.value));
    if(state.metric==="week")points=points.filter((p,i)=>i===points.length-1||monday(p.date)!==monday(points[i+1].date));
    const W=380,H=180,m={t:15,r:12,b:24,l:42},vals=points.map(p=>p.value),lo=Math.min(0,...vals),hi=Math.max(0,...vals),pad=(hi-lo||.02)*.1,y0=lo-pad,y1=hi+pad;
    const x=i=>m.l+(i/Math.max(1,points.length-1))*(W-m.l-m.r),y=v=>m.t+(y1-v)/(y1-y0)*(H-m.t-m.b),ns="http://www.w3.org/2000/svg";
    const svg=document.createElementNS(ns,"svg");svg.setAttribute("viewBox",`0 0 ${W} ${H}`);svg.setAttribute("role","img");svg.setAttribute("aria-label",`${row.label} ${METRICS[state.metric].label} history`);
    const add=(name,attrs,text)=>{const n=document.createElementNS(ns,name);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text!=null)n.textContent=text;svg.appendChild(n);return n;};
    [0,.5,1].forEach(t=>{const v=y0+(y1-y0)*t,yy=y(v);add("line",{x1:m.l,x2:W-m.r,y1:yy,y2:yy,stroke:"#e7e5e4"});add("text",{x:m.l-6,y:yy+3,"text-anchor":"end",fill:"#78716c","font-size":"9"},`${(v*100).toFixed(0)}%`);});
    if(y0<0&&y1>0)add("line",{x1:m.l,x2:W-m.r,y1:y(0),y2:y(0),stroke:"#a8a29e"});
    const path=points.map((p,i)=>`${i?"L":"M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join("");add("path",{d:path,fill:"none",stroke:"#173f72","stroke-width":"2","stroke-linejoin":"round","stroke-linecap":"round"});
    [0,1].forEach(t=>{const p=points[Math.round((points.length-1)*t)];if(p)add("text",{x:x(Math.round((points.length-1)*t)),y:H-7,"text-anchor":t?"end":"start",fill:"#78716c","font-size":"9"},p.date.slice(0,7));});
    const hit=add("rect",{x:m.l,y:m.t,width:W-m.l-m.r,height:H-m.t-m.b,fill:"transparent"});
    hit.addEventListener("mousemove",event=>{const box=svg.getBoundingClientRect(),at=Math.max(0,Math.min(points.length-1,Math.round(((event.clientX-box.left)/box.width*W-m.l)/(W-m.l-m.r)*(points.length-1)))),p=points[at];if(!p)return;tip.textContent=`${row.ticker} · ${p.date} · ${fmt(p.value)}`;tip.style.display="block";tip.style.left=`${event.clientX+12}px`;tip.style.top=`${event.clientY+12}px`;});
    hit.addEventListener("mouseleave",()=>tip.style.display="none");return svg;
  }
  function lines(){
    const grid=document.createElement("div");grid.className="multiples";
    DATA.series.forEach(row=>{const button=document.createElement("button");button.type="button";button.className="mini"+(state.focus===row.id?" focus":"");button.dataset.sector=row.id;button.setAttribute("aria-label",`${row.label} line chart. Return to heatmap.`);const h=document.createElement("h3"),v=document.createElement("span");v.className="latest";v.textContent=fmt(latest(row));h.textContent=row.label;h.prepend(v);button.append(h,lineSvg(row));button.addEventListener("click",()=>{state.focus=row.id;state.view="heatmap";state.cleared=false;render();});grid.appendChild(button);});stage.replaceChildren(grid);
  }
  function render(){
    setButtons();document.getElementById("title").textContent=state.cleared?"Sectors":state.view==="heatmap"?"Sector heatmap":"Sector lines";
    document.getElementById("subtitle").textContent=state.cleared?"Choose Heatmap or Lines to restore the chart.":`${METRICS[state.metric].label} · equal-size sector display`;
    if(state.cleared){const empty=document.createElement("div");empty.className="empty";empty.textContent="Chart cleared. Choose Heatmap or Lines to restore it.";stage.replaceChildren(empty);return;}
    state.view==="heatmap"?heatmap():lines();
  }
  if(!DATA||!Array.isArray(DATA.series)||DATA.series.length!==11){stage.innerHTML='<div class="error">Sector data did not load.</div>';return;}
  document.getElementById("asof").textContent=`through ${DATA.as_of}`;
  document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>{state.view=button.dataset.view;state.cleared=false;render();}));
  document.querySelectorAll("[data-metric]").forEach(button=>button.addEventListener("click",()=>{state.metric=button.dataset.metric;render();}));
  document.querySelectorAll("[data-range]").forEach(button=>button.addEventListener("click",()=>{state.range=button.dataset.range;render();}));
  document.getElementById("clear").addEventListener("click",()=>{state.cleared=true;tip.style.display="none";render();});render();
})();
