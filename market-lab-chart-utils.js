(function(global){
  "use strict";
  const NS="http://www.w3.org/2000/svg";
  const el=(name,attrs,text)=>{const n=document.createElementNS(NS,name);Object.entries(attrs||{}).forEach(([k,v])=>n.setAttribute(k,v));if(text!=null)n.textContent=text;return n;};
  const extent=values=>{let lo=Math.min(...values),hi=Math.max(...values);if(lo===hi){lo-=1;hi+=1;}const pad=(hi-lo)*.08;return[lo-pad,hi+pad];};
  function chart(container,series,options={}){
    container.innerHTML="";
    const width=Math.max(640,container.clientWidth||900),height=options.height||430,m={top:24,right:22,bottom:38,left:58};
    const svg=el("svg",{viewBox:`0 0 ${width} ${height}`,role:"img","aria-label":options.label||"Macro time series"});
    svg.style.width="100%";svg.style.height="auto";container.appendChild(svg);
    const all=series.flatMap(s=>s.points||[]), dates=all.map(p=>Date.parse(p.date)), vals=all.map(p=>p.value).filter(Number.isFinite);
    if(!dates.length||!vals.length){svg.appendChild(el("text",{x:width/2,y:height/2,"text-anchor":"middle",fill:"#78716c"},"No accepted observations for this selection"));return svg;}
    const x0=Math.min(...dates),x1=Math.max(...dates),[y0,y1]=extent(vals),x=d=>m.left+(Date.parse(d)-x0)/(x1-x0||1)*(width-m.left-m.right),y=v=>m.top+(y1-v)/(y1-y0)*(height-m.top-m.bottom);
    for(let i=0;i<5;i++){const v=y0+(y1-y0)*i/4,yy=y(v);svg.appendChild(el("line",{x1:m.left,x2:width-m.right,y1:yy,y2:yy,stroke:"#e7e5e4"}));svg.appendChild(el("text",{x:m.left-9,y:yy+4,"text-anchor":"end",fill:"#78716c","font-size":"11"},options.format?options.format(v):v.toFixed(1)));}
    for(let i=0;i<5;i++){const d=new Date(x0+(x1-x0)*i/4),xx=x(d);svg.appendChild(el("text",{x:xx,y:height-12,"text-anchor":"middle",fill:"#78716c","font-size":"11"},d.toLocaleDateString(undefined,{year:"numeric",month:"short"})));}
    const colors=["#1d7fc4","#d97706","#059669","#7c3aed"];
    series.forEach((s,idx)=>{const pts=s.points.filter(p=>Number.isFinite(p.value));let d="";pts.forEach((p,i)=>d+=(i?"L":"M")+x(p.date).toFixed(1)+","+y(p.value).toFixed(1));svg.appendChild(el("path",{d,fill:"none",stroke:s.color||colors[idx%colors.length],"stroke-width":"2.2","stroke-linejoin":"round","stroke-linecap":"round"}));if(pts.length<180)pts.forEach(p=>svg.appendChild(el("circle",{cx:x(p.date),cy:y(p.value),r:2.1,fill:s.color||colors[idx%colors.length]})));const last=pts[pts.length-1];if(last){const lx=x(last.date),right=lx>width-m.right-120;svg.appendChild(el("text",{x:right?lx-7:lx+7,y:y(last.value)-5,"text-anchor":right?"end":"start",fill:s.color||colors[idx%colors.length],"font-size":"11","font-weight":"600"},s.title));}});
    const cursor=el("line",{y1:m.top,y2:height-m.bottom,stroke:"#78716c","stroke-dasharray":"3 3",visibility:"hidden"});svg.appendChild(cursor);
    const hit=el("rect",{x:m.left,y:m.top,width:width-m.left-m.right,height:height-m.top-m.bottom,fill:"transparent",tabindex:"0"});svg.appendChild(hit);
    hit.addEventListener("mousemove",event=>{const box=svg.getBoundingClientRect(),mx=(event.clientX-box.left)*width/box.width,at=x0+(mx-m.left)/(width-m.left-m.right)*(x1-x0),rows=[];series.forEach(s=>{const candidates=s.points.filter(p=>Date.parse(p.date)<=at);const p=candidates[candidates.length-1];if(p)rows.push({title:s.title,date:p.date,value:p.value,color:s.color});});if(!rows.length)return;const px=x(rows[0].date);cursor.setAttribute("x1",px);cursor.setAttribute("x2",px);cursor.setAttribute("visibility","visible");options.onCursor&&options.onCursor(rows,event);});
    hit.addEventListener("mouseleave",()=>{cursor.setAttribute("visibility","hidden");options.onCursor&&options.onCursor(null);});
    return svg;
  }
  function png(svg,filename,footer){const xml=new XMLSerializer().serializeToString(svg),img=new Image(),blob=new Blob([xml],{type:"image/svg+xml"}),url=URL.createObjectURL(blob);img.onload=()=>{const box=svg.viewBox.baseVal,canvas=document.createElement("canvas");canvas.width=box.width*2;canvas.height=(box.height+40)*2;const ctx=canvas.getContext("2d");ctx.scale(2,2);ctx.fillStyle="#fff";ctx.fillRect(0,0,box.width,box.height+40);ctx.drawImage(img,0,0,box.width,box.height);ctx.fillStyle="#78716c";ctx.font="11px system-ui";ctx.fillText(footer||"",16,box.height+25);canvas.toBlob(out=>{const a=document.createElement("a");a.href=URL.createObjectURL(out);a.download=filename;a.click();URL.revokeObjectURL(a.href);});URL.revokeObjectURL(url);};img.src=url;}
  global.MarketLabChart={chart,png};
})(window);
