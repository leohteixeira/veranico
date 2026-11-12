(function(){
"use strict";
const {REG,N,CARRIER,km,build}=window.VR,I=window.VR_I;
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const store={get(k){try{return localStorage.getItem(k)}catch(e){return null}},set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
const IC={check:'<svg class="ic" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.6l3.2 3L13 4.6"/></svg>',
  warn:'<svg class="ic" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2.2 14.6 13.6H1.4Z"/><path d="M8 6.6v3.2M8 11.6v.2"/></svg>',
  clock:'<svg class="ic" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6"/><path d="M8 4.6V8l2.4 1.6"/></svg>',
  send:'<svg class="ic" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 13V3.4M3.6 7.6 8 3.2l4.4 4.4"/></svg>'};

Object.assign(I.en,{pv_dir:"Direction",pv_note2:"Three directions for the same product. The map imagery is real (Sentinel-2 and relief); weather values are synthetic.",
  b_ter:"Relief",r_surf:"Surface",r_cells:"Cells",tab_risk:"Risk",step_of:"Step {k} of 6 · {n}",
  risk_me:"The insured cell pays in",risk_me_s:"Insured cell in the {y} season",risk_nb:"The 8 neighbouring cells range from {a} to {b}.",risk_nb_t:"Neighbourhood, cells of about 9 km",
  tl_hint:"Drag across the seasons",cube:"ERA5-Land grid · 0.1° · {n} cells",lg_lo:"rarely pays",lg_hi:"pays often",attr_short:"Imagery: Sentinel-2 cloudless 2024 by EOX (modified Copernicus Sentinel data), CC BY-NC-SA 4.0. Relief: EOX, © OpenStreetMap contributors.",
  attr_map:"Imagery: Sentinel-2 cloudless 2024 by EOX IT Services GmbH (contains modified Copernicus Sentinel data 2024), CC BY-NC-SA 4.0. Relief: EOX Terrain Light, data © OpenStreetMap contributors and others."});
Object.assign(I.pt,{pv_dir:"Direção",pv_note2:"Três direções para o mesmo produto. As imagens do mapa são reais (Sentinel-2 e relevo); os valores de clima são sintéticos.",
  b_ter:"Relevo",r_surf:"Superfície",r_cells:"Células",tab_risk:"Risco",step_of:"Etapa {k} de 6 · {n}",
  risk_me:"A célula segurada paga em",risk_me_s:"Célula segurada na safra {y}",risk_nb:"As 8 células vizinhas vão de {a} a {b}.",risk_nb_t:"Vizinhança, células de cerca de 9 km",
  tl_hint:"Arraste pelas safras",cube:"Grade ERA5-Land · 0,1° · {n} células",lg_lo:"paga raramente",lg_hi:"paga com frequência",attr_short:"Imagens: Sentinel-2 cloudless 2024, EOX (dados Copernicus Sentinel modificados), CC BY-NC-SA 4.0. Relevo: EOX, © colaboradores do OpenStreetMap.",
  attr_map:"Imagens: Sentinel-2 cloudless 2024, da EOX IT Services GmbH (contém dados Copernicus Sentinel 2024 modificados), CC BY-NC-SA 4.0. Relevo: EOX Terrain Light, dados © colaboradores do OpenStreetMap e outros."});

/* towns outside the weather cube, for context on the wider map */
const CTX={mg:[["Belo Horizonte",-19.92,-43.94],["Passos",-20.72,-46.61],["São João del-Rei",-21.14,-44.26],["Juiz de Fora",-21.76,-43.35],["Campinas",-22.91,-47.06],["Ribeirão Preto",-21.18,-47.81]],
  mt:[["Nova Mutum",-13.83,-56.08],["Nova Ubiratã",-12.99,-55.25],["Juara",-11.25,-57.52]],
  sp:[["Uberaba",-19.75,-47.93],["São José do Rio Preto",-20.82,-49.38],["Bauru",-22.31,-49.07],["Campinas",-22.91,-47.06],["Barretos",-20.56,-48.57]]};

/* map paint per direction: colour stops are [r,g,b,alpha], low to high */
const DIR={
 noturno:{base:"sat",bg:"#0a0e13",veil:{sat:"rgba(6,10,16,.52)",ter:"rgba(8,12,18,.80)"},out:{sat:"rgba(6,10,16,.32)",ter:"rgba(6,10,16,.3)"},sw:{sat:"#17201c",ter:"#2a2d31"},
  seq:[[58,32,96,.32],[120,44,130,.48],[190,60,112,.62],[236,104,64,.74],[248,168,52,.84],[255,230,128,.92]],
  div:[[255,218,110,.92],[242,124,62,.80],[172,62,112,.58],[70,72,92,.26],[46,104,170,.56],[52,150,222,.76],[104,200,250,.88]],
  label:"#eef2f6",halo:"rgba(6,10,16,.88)",mark:"#ffffff",markInk:"#0a0e13",grid:"rgba(255,255,255,.14)",cube:"rgba(255,255,255,.6)"},
 atlas:{base:"ter",bg:"#efeadf",veil:{sat:"rgba(250,246,238,.40)",ter:"rgba(255,250,240,.12)"},out:{sat:"rgba(250,246,238,.34)",ter:"rgba(239,234,223,.46)"},sw:{sat:"#a9b0a0",ter:"#f1ede4"},
  seq:[[251,233,200,.60],[246,201,138,.70],[236,159,90,.76],[217,113,60,.82],[179,71,42,.86],[125,38,23,.90]],
  div:[[163,57,31,.88],[217,113,60,.78],[241,192,143,.68],[232,228,220,.50],[167,211,214,.68],[78,163,176,.80],[18,112,127,.90]],
  label:"#1b2428",halo:"rgba(255,253,248,.92)",mark:"#143c44",markInk:"#fffdf8",grid:"rgba(27,36,40,.13)",cube:"rgba(27,36,40,.55)"},
 campo:{base:"sat",bg:"#12281d",veil:{sat:"rgba(10,24,16,.16)",ter:"rgba(248,242,228,.10)"},out:{sat:"rgba(10,24,16,.38)",ter:"rgba(236,228,208,.5)"},sw:{sat:"#2f4a30",ter:"#eee9dc"},
  seq:[[255,238,165,.20],[255,208,95,.42],[255,162,52,.60],[250,112,40,.74],[226,62,40,.85],[168,26,46,.93]],
  div:[[200,45,40,.88],[245,120,50,.70],[255,200,110,.48],[235,235,228,.24],[150,225,235,.46],[60,190,220,.68],[10,140,190,.88]],
  label:"#fbf6ea",halo:"rgba(12,28,20,.88)",mark:"#fbf6ea",markInk:"#12281d",grid:"rgba(255,255,255,.2)",cube:"rgba(255,255,255,.72)"}};
const FB=[.06,.12,.18,.24,.32],FO=[0,.40],AB=[-.4,-.2,-.05,.05,.2,.4],AO=[-.6,.6];
const cls=(v,br)=>{let q=0;while(q<br.length&&v>=br[q])q++;return q};
function pos(v,br,o){const k=cls(v,br),lo=k===0?o[0]:br[k-1],hi=k===br.length?o[1]:br[k];return k+Math.max(0,Math.min(1,(v-lo)/(hi-lo)))}
function mix(st,p){const x=Math.max(0,Math.min(st.length-1,p-.5)),a=Math.floor(x),b=Math.min(st.length-1,a+1),f=x-a;return [0,1,2,3].map(q=>st[a][q]+(st[b][q]-st[a][q])*f)}
const rgba=c=>"rgba("+Math.round(c[0])+","+Math.round(c[1])+","+Math.round(c[2])+","+c[3].toFixed(3)+")";
const swatch=(c,base)=>"background:linear-gradient("+rgba(c)+","+rgba(c)+"),"+base;

/* ---------- state ---------- */
const S={lang:store.get("vr-lang")||((navigator.language||"pt").toLowerCase().startsWith("en")?"en":"pt"),dir:store.get("vr-dir")||"noturno",
  view:"app",region:"mg",tab:"risk",metric:"freq",season:null,base:"sat",render:"surf",step:4,run:0,ext:false,appr:"none",pstate:"normal",audit:[],token:0};
if(!DIR[S.dir])S.dir="noturno";S.base=DIR[S.dir].base;
const cur=()=>build(S.region);
const t=(k,v)=>{let s=I[S.lang][k];if(s===undefined)s=I.en[k];if(s===undefined)return k;if(v)for(const q in v)s=s.split("{"+q+"}").join(v[q]);return s};
const loc=()=>S.lang==="pt"?"pt-BR":"en-US";
const nf=o=>new Intl.NumberFormat(loc(),o);
const money=c=>nf({style:"currency",currency:"BRL"}).format(c/100);
const moneyK=c=>nf({style:"currency",currency:"BRL",notation:"compact",maximumFractionDigits:0}).format(c/100);
const pct=(x,d=1)=>nf({style:"percent",minimumFractionDigits:d,maximumFractionDigits:d}).format(x);
const mm=v=>nf({maximumFractionDigits:0}).format(v)+" mm";
const mm1=v=>nf({minimumFractionDigits:1,maximumFractionDigits:1}).format(v)+" mm";
const kmf=d=>nf({minimumFractionDigits:1,maximumFractionDigits:1}).format(d)+" km";
const ll=(la,lo)=>nf({minimumFractionDigits:2,maximumFractionDigits:2}).format(Math.abs(la))+"°S "+nf({minimumFractionDigits:2,maximumFractionDigits:2}).format(Math.abs(lo))+(S.lang==="pt"?"°O":"°W");
const now=()=>new Date().toISOString().slice(11,19);
const reduced=()=>window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep=ms=>new Promise(r=>setTimeout(r,reduced()?0:ms));
function seedAudit(){const d=cur();S.audit=[];if(S.step>=4)S.audit.push([now(),"agent","au_q",{}]);if(S.step>=5)S.audit.push([now(),"agent","au_ts",{}]);if(S.step>=6)S.audit.push([now(),"agent","au_sub",{s:d.s,c:CARRIER}])}
function qStatus(){if(S.step<4)return null;if(S.step<6)return "draft";return S.appr==="none"||S.appr==="pending"?"pending":S.appr}

/* ---------- map ---------- */
const IMG={};
function getImg(k,cb){let o=IMG[k];if(!o){o=IMG[k]={im:new Image(),ok:false,cbs:new Set()};o.im.onload=()=>{o.ok=true;o.cbs.forEach(f=>f());o.cbs.clear()};o.im.src="vr/maps/"+k+".jpg"}if(!o.ok&&cb)o.cbs.add(cb);return o.ok?o.im:null}
const mY=lat=>Math.log(Math.tan(Math.PI/4+lat*Math.PI/360));
const SURF={};
function surface(d,freq){
  const key=[S.region,freq?"f":"a"+S.season,S.dir].join("|");if(SURF.key===key)return SURF.cv;
  const M=96,oc=SURF.cv||(SURF.cv=document.createElement("canvas"));oc.width=oc.height=M;
  const og=oc.getContext("2d"),im=og.createImageData(M,M),D=DIR[S.dir],V=d.cells.map(c=>freq?c.freq:(c.idx[S.season]-c.med)/c.med);
  for(let b=0;b<M;b++)for(let a=0;a<M;a++){
    const gx=Math.max(0,Math.min(N-1,(a+.5)/M*N-.5)),gy=Math.max(0,Math.min(N-1,(b+.5)/M*N-.5)),i0=Math.floor(gx),j0=Math.floor(gy),i1=Math.min(N-1,i0+1),j1=Math.min(N-1,j0+1),fx=gx-i0,fy=gy-j0;
    const v=(V[j0*N+i0]*(1-fx)+V[j0*N+i1]*fx)*(1-fy)+(V[j1*N+i0]*(1-fx)+V[j1*N+i1]*fx)*fy,col=freq?mix(D.seq,pos(v,FB,FO)):mix(D.div,pos(v,AB,AO)),o=(b*M+a)*4;
    const e=Math.min(a,b,M-1-a,M-1-b),fe=e>=3?1:(e+1)/4;im.data[o]=col[0];im.data[o+1]=col[1];im.data[o+2]=col[2];im.data[o+3]=col[3]*255*fe}
  og.putImageData(im,0,0);SURF.key=key;return oc;
}
function MapView(box,padFn){
  const cv=$("canvas",box);let hover=null,tip=null,G=null;
  function geom(){
    const d=cur(),c=d.c,W=box.clientWidth,H=box.clientHeight,v={w:c.west-1.6,e:c.west+3.6,n:c.north+.6,s:c.north-2.6};
    const im=getImg(S.region+"-"+S.base,draw),iw=im?im.naturalWidth:1893,ih=im?im.naturalHeight:1250;
    const u=lon=>(lon-v.w)/(v.e-v.w),vv=lat=>(mY(v.n)-mY(lat))/(mY(v.n)-mY(v.s));
    const p=padFn?padFn():{l:0,r:0,t:0,b:0},fw=Math.max(60,W-p.l-p.r),fh=Math.max(60,H-p.t-p.b);
    const u0=u(c.west),u1=u(c.west+2),v0=vv(c.north),v1=vv(c.north-2),cover=Math.max(W/iw,H/ih),fit=Math.min(fw/((u1-u0)*iw),fh/((v1-v0)*ih))*.8;
    const sc=Math.max(cover,Math.min(fit,cover*2.2));
    const ox=Math.min(0,Math.max(W-iw*sc,p.l+fw/2-(u0+u1)/2*iw*sc)),oy=Math.min(0,Math.max(H-ih*sc,p.t+fh/2-(v0+v1)/2*ih*sc));
    const X=lon=>ox+u(lon)*iw*sc,Y=lat=>oy+vv(lat)*ih*sc,cx=[],cy=[];
    for(let i=0;i<=N;i++){cx.push(X(c.west+i*.1));cy.push(Y(c.north-i*.1))}
    return G={d,c,W,H,im,iw,ih,sc,ox,oy,X,Y,cx,cy};
  }
  function draw(){
    const g0=geom(),{d,c,W,H,cx,cy}=g0;if(!W||!H)return;const dpr=Math.min(2,window.devicePixelRatio||1);
    if(cv.width!==Math.round(W*dpr)||cv.height!==Math.round(H*dpr)){cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr)}
    const g=cv.getContext("2d"),D=DIR[S.dir],sans=(getComputedStyle(box).getPropertyValue("--sans")||"sans-serif").trim();
    g.setTransform(dpr,0,0,dpr,0,0);g.globalAlpha=1;g.fillStyle=D.bg;g.fillRect(0,0,W,H);
    if(g0.im){g.imageSmoothingEnabled=true;g.imageSmoothingQuality="high";g.drawImage(g0.im,g0.ox,g0.oy,g0.iw*g0.sc,g0.ih*g0.sc)}
    g.fillStyle=D.veil[S.base];g.fillRect(0,0,W,H);
    const x0=cx[0],x1=cx[N],y0=cy[0],y1=cy[N];
    g.fillStyle=D.out[S.base];g.beginPath();g.rect(0,0,W,H);g.rect(x0,y0,x1-x0,y1-y0);g.fill("evenodd");
    const freq=S.metric==="freq"||S.season===null;
    if(S.render==="surf")g.drawImage(surface(d,freq),x0,y0,x1-x0,y1-y0);
    else for(const cl of d.cells){g.fillStyle=rgba(freq?D.seq[cls(cl.freq,FB)]:D.div[cls((cl.idx[S.season]-cl.med)/cl.med,AB)]);g.fillRect(cx[cl.i],cy[cl.j],cx[cl.i+1]-cx[cl.i]+.5,cy[cl.j+1]-cy[cl.j]+.5)}
    g.strokeStyle=D.grid;g.lineWidth=1;g.globalAlpha=S.render==="surf"?.5:1;g.beginPath();
    for(let i=1;i<N;i++){const a=Math.round(cx[i])+.5,b=Math.round(cy[i])+.5;g.moveTo(a,y0);g.lineTo(a,y1);g.moveTo(x0,b);g.lineTo(x1,b)}
    g.stroke();g.globalAlpha=1;g.strokeStyle=D.cube;g.lineWidth=1.2;g.strokeRect(x0,y0,x1-x0,y1-y0);
    const txt=(s,x,y,font,fill,al)=>{g.font=font;g.textAlign=al||"left";g.textBaseline="middle";g.lineJoin="round";g.lineWidth=3.5;g.strokeStyle=D.halo;g.strokeText(s,x,y);g.fillStyle=fill;g.fillText(s,x,y)};
    const small=W<520;
    txt(t("cube",{n:N*N}),x0+9,y0+13,"500 "+(small?9.5:11)+"px "+sans,D.label);
    const fx=g0.X(c.farm[1]),fy=g0.Y(c.farm[0]);
    g.font="500 "+(small?10.5:12.5)+"px "+sans;
    for(const tn of c.towns.concat(CTX[S.region]||[])){const x=g0.X(tn[2]),y=g0.Y(tn[1]);if(x<4||y<4||x>W-4||y>H-4)continue;
      g.beginPath();g.arc(x,y,3.4,0,6.2832);g.fillStyle=D.halo;g.fill();g.beginPath();g.arc(x,y,2,0,6.2832);g.fillStyle=D.label;g.fill();
      const tw=g.measureText(tn[0]).width,left=x+8+tw>W-4||(Math.abs(x-fx)<90&&Math.abs(y-fy)<26&&x<=fx+8);
      txt(tn[0],left?x-7:x+7,y,"500 "+(small?10.5:12.5)+"px "+sans,D.label,left?"right":"left")}
    const ix=cx[d.fi],iy=cy[d.fj],iw=cx[d.fi+1]-ix,ih=cy[d.fj+1]-iy;
    g.lineJoin="miter";g.strokeStyle=D.halo;g.lineWidth=5;g.strokeRect(ix,iy,iw,ih);g.strokeStyle=D.mark;g.lineWidth=2;g.strokeRect(ix,iy,iw,ih);
    const R=small?7:9;
    if(hover&&!(hover.i===d.fi&&hover.j===d.fj)){const hx=(cx[hover.i]+cx[hover.i+1])/2,hy=(cy[hover.j]+cy[hover.j+1])/2,cl=d.cells[hover.j*N+hover.i];
      g.strokeStyle=D.halo;g.lineWidth=4.5;g.beginPath();g.moveTo(fx,fy);g.lineTo(hx,hy);g.stroke();
      g.strokeStyle=D.mark;g.lineWidth=1.8;g.setLineDash([6,5]);g.beginPath();g.moveTo(fx,fy);g.lineTo(hx,hy);g.stroke();g.setLineDash([]);
      g.strokeStyle=D.halo;g.lineWidth=4;g.strokeRect(cx[hover.i],cy[hover.j],cx[hover.i+1]-cx[hover.i],cy[hover.j+1]-cy[hover.j]);
      g.strokeStyle=D.label;g.lineWidth=1.6;g.strokeRect(cx[hover.i],cy[hover.j],cx[hover.i+1]-cx[hover.i],cy[hover.j+1]-cy[hover.j]);
      txt(kmf(km(c.farm,[cl.lat,cl.lon])),(fx+hx)/2,(fy+hy)/2-10,"600 12px "+sans,D.label,"center")}
    g.fillStyle=D.halo;g.beginPath();g.arc(fx,fy,R+2.5,0,6.2832);g.fill();
    g.strokeStyle=D.mark;g.lineWidth=2.5;g.beginPath();g.arc(fx,fy,R,0,6.2832);g.stroke();g.fillStyle=D.mark;g.beginPath();g.arc(fx,fy,3,0,6.2832);g.fill();
    const lb0=t("farm"),lb=lb0[0]+lb0.slice(1).toLowerCase();g.font="700 "+(small?10.5:12)+"px "+sans;const lw=g.measureText(lb).width+14,lh=small?18:20,lx=fx+R+8+lw>W-4?fx-R-8-lw:fx+R+8,ly=fy-R-lh+2;
    g.fillStyle=D.mark;g.beginPath();if(g.roundRect)g.roundRect(lx,ly,lw,lh,lh/2);else g.rect(lx,ly,lw,lh);g.fill();
    g.fillStyle=D.markInk;g.textAlign="center";g.textBaseline="middle";g.fillText(lb,lx+lw/2,ly+lh/2+.5);
  }
  function showTip(e){
    if(!G)return;const b=box.getBoundingClientRect(),x=e.clientX-b.left,y=e.clientY-b.top;let i=-1,j=-1;
    for(let k=0;k<N;k++){if(x>=G.cx[k]&&x<G.cx[k+1])i=k;if(y>=G.cy[k]&&y<G.cy[k+1])j=k}
    if(i<0||j<0){hide();return}
    if(!hover||hover.i!==i||hover.j!==j){hover={i,j};draw()}
    const d=cur(),c=d.cells[j*N+i];if(!tip){tip=document.createElement("div");tip.className="tip";box.appendChild(tip)}
    const l2=S.metric==="freq"||S.season===null?t("tip_f",{f:pct(c.freq)}):t("tip_s",{v:mm(c.idx[S.season]),a:pct((c.idx[S.season]-c.med)/c.med,0)});
    tip.innerHTML="<b>"+ll(c.lat,c.lon)+"</b>"+l2+"<br>"+t("tip_d",{d:kmf(km(d.c.farm,[c.lat,c.lon]))});
    const tw=tip.offsetWidth,th=tip.offsetHeight;tip.style.left=Math.max(4,Math.min(b.width-tw-4,x+16))+"px";tip.style.top=Math.max(4,Math.min(b.height-th-4,y+16>b.height-th-4?y-th-12:y+16))+"px";
  }
  function hide(){if(tip){tip.remove();tip=null}if(hover){hover=null;draw()}}
  cv.addEventListener("pointermove",showTip);cv.addEventListener("pointerdown",showTip);cv.addEventListener("pointerleave",hide);
  return {draw,hide};
}
const zero={l:0,r:0,t:0,b:0};
function padApp(){const box=$("#mapA"),st=$("#view-app");if(getComputedStyle(box).position!=="absolute")return zero;const b=box.getBoundingClientRect(),r=s=>$(s,st).getBoundingClientRect();
  return {l:r(".chat").right-b.left+16,r:b.right-r(".info").left+16,t:r(".top").bottom-b.top+28,b:b.bottom-r(".time").top+16}}
function padLand(){return {l:0,r:0,t:8,b:0}}

/* ---------- renderers ---------- */
function applyText(){$$("[data-t]").forEach(e=>{e.textContent=t(e.dataset.t)});document.documentElement.lang=loc();$("#lHead").innerHTML=t("l_head")}
function press(id,val){$$("#"+id+" button").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.v===val)))}

function renderSteps(){
  const sub=S.appr==="submitted";let h="",at=0;
  for(let k=1;k<=6;k++){const done=k<=Math.min(S.step,5)||(k===6&&sub),curr=!done&&((S.run===k)||(S.run===0&&k===S.step+1)||(k===6&&S.step===6));if(curr)at=k;h+='<li class="'+(done?"done":curr?"cur":"todo")+'"></li>'}
  $("#steps").innerHTML=h;$("#stepL").innerHTML=sub?"<b>"+t("c_end")+"</b>":t("step_of",{k:at||1,n:"<b>"+t("c"+(at||1))+"</b>"});
}
const TD={resolve_location:184,get_weather_history:642,backtest_index:96,price_cover:413,find_extreme_seasons:58,draft_term_sheet:877,request_submission:121};
const fig=(v,go,k)=>'<button type="button" class="fig" data-go="'+go+'" data-k="'+(k||"")+'">'+v+"</button>";
function toolRow(k,num,name,args,sum){
  const running=S.run===k;return '<details class="tool"><summary><span class="n">'+(num||"·")+'</span><span class="nm">'+name+'<span class="sm">'+(running?"":sum)+'</span></span><span class="st'+(running?"":" ok")+'">'+
    (running?'<span class="spin"></span>'+t("running"):IC.check+'<span class="num">'+TD[name]+" ms</span>")+"</span></summary><pre>"+JSON.stringify(args,null,1)+"</pre></details>";
}
function renderChat(){
  const d=cur(),c=d.c,vis=k=>S.step>=k||S.run===k,q='<button type="button" class="qtag" data-go="quote">'+d.q+"</button>";let h="",users=0;
  const user=x=>{users++;return '<div class="msg user"><span class="who">'+t("you")+"</span><p>"+x+"</p></div>"},agent=x=>'<div class="msg agent"><span class="who">'+t("agent")+"</span>"+x+"</div>";
  const base={dataset_id:"cube:"+c.id,index:"rainfall_below",window:c.win,trigger_mm:c.trig,exit_mm:c.exit,limit_cents:c.limit};
  if(S.step===0&&!S.run){
    h+='<div class="first"><h3>'+t("first_h")+"</h3><p>"+t("first_p")+'</p><div class="ex">'+Object.keys(REG).map(k=>'<button type="button" data-ex="'+k+'"><b>'+REG[k].ex[S.lang]+"</b>"+REG[k].u[S.lang]+"</button>").join("")+"</div></div>";
  }else{
    h+=user(c.u[S.lang]);let rows="";
    if(vis(1))rows+=toolRow(1,1,"resolve_location",{query:c.place},t("t_res",{p:c.place,ll:ll(c.farm[0],c.farm[1])}));
    if(vis(2))rows+=toolRow(2,2,"get_weather_history",{lat:c.farm[0],lon:c.farm[1]},t("t_hist",{id:c.id,y0:d.years[0],y1:d.years[d.n-1]}));
    if(vis(3))rows+=toolRow(3,3,"backtest_index",base,t("t_bt",{n:d.n,f:pct(d.me.freq)}));
    if(rows)h+='<div class="tools">'+rows+"</div>";
    if(S.step>=3)h+=agent("<p>"+t("a_bt",{n:d.n,y0:d.years[0],y1:d.years[d.n-1],win:c.winL[S.lang],trig:fig(mm(c.trig),"quote","trig"),k:fig(d.cnt,"history","freq"),f:fig(pct(d.me.freq),"history","freq"),
      burn:fig(money(d.burn),"history","burn"),maxp:fig(money(d.mx),"history","max"),maxy:d.years[d.mxk],trend:d.sig?t("a_trend",{s:fig(mm1(d.slope10),"history","trend")}):""})+"</p>");
    if(vis(4))h+=user(t("u2"))+'<div class="tools">'+toolRow(4,4,"price_cover",Object.assign({},base,{n:100000,seed:42}),t("t_pr",{q:d.q,prem:money(d.sim.prem)}))+"</div>";
    if(S.step>=4){let x="<p>"+t("a_q",{q,el:fig(money(d.sim.el),"quote","el"),q10:fig(money(d.sim.q10),"quote","q10"),q100:fig(money(d.sim.q100),"quote","q100"),prem:fig(money(d.sim.prem),"quote","prem"),
        rol:fig(pct(d.sim.rol,2),"quote","rol"),trig:fig(mm(c.trig),"quote","trig"),exit:fig(mm(c.exit),"quote","exit"),n:d.n});
      if(S.pstate==="flag")x+=" "+t("flag_s",{v:'<span class="fig bad">'+money(Math.round(d.sim.prem/2/100)*100)+"</span>"});
      x+="</p>";if(S.pstate==="flag")x+='<div class="note warn">'+IC.warn+"<span>"+t("flag_t")+"</span></div>";h+=agent(x)}
    if(S.ext)h+=user(t("uext"))+'<div class="tools">'+toolRow(-1,0,"find_extreme_seasons",{dataset_id:"cube:"+c.id,index:"rainfall_below",window:c.win,top_n:3},t("t_ext"))+"</div>"+
      agent("<p>"+t("a_ext")+'</p><div class="chips" style="padding:0">'+d.ext.map(e=>'<button type="button" class="chip num" data-season="'+e.k+'">'+t("a_ext_i",{y:d.years[e.k],v:mm(d.me.idx[e.k]),rp:e.rp})+"</button>").join("")+"</div>");
    if(vis(5))h+=user(t("u3"))+'<div class="tools">'+toolRow(5,5,"draft_term_sheet",{quote_id:d.q},t("t_ts"))+"</div>";
    if(S.step>=5)h+=agent("<p>"+t("a_ts",{q})+"</p>");
    if(vis(6))h+=user(t("u4",{c:CARRIER}))+'<div class="tools">'+toolRow(6,6,"request_submission",{quote_id:d.q,carrier:"aurora-re-mock"},t("t_sub",{s:d.s}))+"</div>";
    if(S.step>=6){h+=agent("<p>"+t("a_sub",{s:'<span class="sid num">'+d.s+"</span>",c:CARRIER})+"</p>");
      if(S.appr==="none"||S.appr==="pending")h+='<div class="note wait">'+IC.clock+"<span>"+t("n_wait")+' <button type="button" class="lnk" data-go="approvals">'+t("open_apr")+"</button></span></div>";
      else if(S.appr==="approved")h+='<div class="note wait"><span class="spin"></span><span>'+t("ap_deliv")+"</span></div>";
      else if(S.appr==="submitted")h+='<div class="note ok">'+IC.check+"<span>"+t("n_done",{r:d.rc})+"</span></div>";
      else h+='<div class="note warn">'+IC.warn+"<span>"+t("n_rej")+"</span></div>"}
  }
  const box=$("#msgs");box.innerHTML=h;box.scrollTop=box.scrollHeight;
  $("#meter").textContent=t("ch_meter",{n:S.pstate==="quota"?0:Math.max(0,15-users),m:15});
  let ch="";if(!S.run&&S.pstate!=="quota"){if(S.step===4){if(!S.ext)ch+='<button type="button" class="chip" data-act="ext">'+t("s_ext")+"</button>";ch+='<button type="button" class="chip" data-act="next">'+t("s_ts")+"</button>"}
    else if(S.step===5)ch+='<button type="button" class="chip" data-act="next">'+t("s_sub",{c:CARRIER})+"</button>"}
  $("#chips").innerHTML=ch;$("#chips").hidden=!ch;
  $("#comp").innerHTML=S.pstate==="quota"?'<div class="note warn">'+IC.warn+"<span>"+t("quota_t")+'</span></div><div><button type="button" class="btn" data-act="replay">'+t("quota_b")+"</button></div>":
    '<div class="row"><textarea id="inMsg" rows="2" aria-label="'+t("ph")+'" placeholder="'+t("ph")+'"></textarea><button class="send" type="submit" aria-label="'+t("send")+'">'+IC.send+"</button></div><small>"+t("comp_note")+"</small>";
}

function renderRisk(){
  const d=cur(),D=DIR[S.dir],freq=S.metric==="freq"||S.season===null,k=S.season,base=D.sw[S.base];
  $("#rkLab").textContent=freq?t("risk_me"):t("risk_me_s",{y:d.years[k]});
  $("#rkVal").innerHTML=freq?pct(d.me.freq)+" <small>"+(S.lang==="pt"?"das safras":"of seasons")+"</small>":mm(d.me.idx[k])+" <small>"+money(d.pays[k])+"</small>";
  const vals=d.nb.map(x=>freq?x.cell.freq:x.cell.idx[k]),lo=Math.min.apply(null,vals),hi=Math.max.apply(null,vals);
  $("#rkNb").innerHTML=t("risk_nb",{a:"<b>"+(freq?pct(lo):mm(lo))+"</b>",b:"<b>"+(freq?pct(hi):mm(hi))+"</b>"});
  const st=freq?D.seq:D.div,br=freq?FB:AB;
  $("#lg").innerHTML='<div class="lgbar">'+st.map(c=>'<i style="'+swatch(c,base)+'"></i>').join("")+'</div><div class="lgt" style="padding:0 '+(50/st.length)+'%">'+
    br.map(b=>"<span>"+(!freq&&b>0?"+":"")+pct(b,0)+"</span>").join("")+'</div><div class="lge"><span>'+t(freq?"lg_lo":"lg_dry")+"</span><span>"+t(freq?"lg_hi":"lg_wet")+"</span></div>";
  const by={};d.nb.forEach(x=>{by[x.dir]=x.cell});
  $("#nbg").innerHTML=[7,0,1,6,-1,2,5,4,3].map(q=>{const cl=q<0?d.me:by[q];if(!cl)return "<div></div>";
    const col=freq?D.seq[cls(cl.freq,FB)]:D.div[cls((cl.idx[k]-cl.med)/cl.med,AB)];
    return "<div"+(q<0?' class="me"':"")+'><i style="'+swatch(col,base)+'"></i><span><small>'+(q<0?t("nb_me"):t("dirs")[q])+"</small>"+(freq?pct(cl.freq):mm(cl.idx[k]))+"</span></div>"}).join("");
  $("#readA").innerHTML=freq?t("r_all",{n:d.n}):t("r_season",{y:d.years[k],v:mm(d.me.idx[k]),p:money(d.pays[k]),c:d.paid[k],t:N*N});
  $("#lCap").innerHTML=t("l_cap",{reg:d.c.name,f:pct(d.me.freq),d:kmf(d.far.d),dir:t("dirs")[d.far.dir],f2:pct(d.far.cell.freq)});
}
function renderTimeline(s){
  const w=$("#tl"+s),el=$(".tl",w),d=cur(),r=$("#rng"+s),all=S.season===null;r.max=d.n-1;r.value=all?d.n-1:S.season;
  $("#yr"+s).textContent=all?d.years[0]+"–"+d.years[d.n-1]:d.years[S.season];$("#btnAll"+(s==="A"?"":"L")).hidden=all;
  const W=el.clientWidth;if(!W)return;const H=46,HB=15,sl=W/d.n,bw=Math.max(1.5,Math.min(12,sl-1.5));let mx=0;for(const v of d.me.idx)mx=Math.max(mx,v);
  const y=v=>H-(v/mx)*(H-6);let h='<svg viewBox="0 0 '+W+" "+(H+HB)+'" width="'+W+'" height="'+(H+HB)+'" aria-hidden="true">';
  for(let k=0;k<d.n;k++){const x=k*sl+(sl-bw)/2,yy=y(d.me.idx[k]);h+='<rect x="'+x.toFixed(1)+'" y="'+yy.toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+(H-yy).toFixed(1)+'" rx="'+Math.min(2,bw/2).toFixed(1)+'" fill="var('+(d.pays[k]>0?"--pay":"--bar")+')"'+(!all&&S.season!==k?' opacity=".5"':"")+"/>"}
  h+='<line x1="0" x2="'+W+'" y1="'+y(d.c.trig).toFixed(1)+'" y2="'+y(d.c.trig).toFixed(1)+'" stroke="var(--ink-3)" stroke-dasharray="3 3" stroke-width="1"/>';
  const every=W<340?20:10;d.years.forEach((yr,k)=>{if(yr%every===0)h+='<text x="'+Math.max(13,Math.min(W-13,k*sl+sl/2)).toFixed(1)+'" y="'+(H+12)+'" text-anchor="middle">'+yr+"</text>"});
  if(!all){const x=(S.season*sl+sl/2).toFixed(1);h+='<line x1="'+x+'" x2="'+x+'" y1="0" y2="'+H+'" stroke="var(--ink)" stroke-width="1.5"/>'}
  el.innerHTML=h+"</svg>";el._geo={sl,n:d.n};
}

let hHover=null;
function renderHistory(){
  const d=cur(),c=d.c,el=$("#hist");$("#hiSub").textContent=t("hi_sub",{win:c.winL[S.lang],n:d.n});
  if(!el.clientWidth)return;
  const W=el.clientWidth,ml=36,mr=W<560?6:92,mt=20,H1=W<560?170:210,gp=34,H2=70,mb=22,H=mt+H1+gp+H2+mb,iw=W-ml-mr,sl=iw/d.n,bw=Math.max(1.5,Math.min(24,sl-2));
  let ymax=0;for(const v of d.me.idx)ymax=Math.max(ymax,v);const stepv=ymax>600?200:ymax>300?100:50;ymax=Math.ceil(ymax/stepv)*stepv;
  const y1=v=>mt+H1-(v/ymax)*H1,y2=v=>mt+H1+gp+H2-(v/c.limit)*H2,x=k=>ml+k*sl+(sl-bw)/2,rr=Math.min(4,bw/2);
  const bar=(xx,yy,y0)=>yy>=y0-.2?"":"M"+xx.toFixed(1)+","+y0+"V"+(yy+rr).toFixed(1)+"Q"+xx.toFixed(1)+","+yy.toFixed(1)+" "+(xx+rr).toFixed(1)+","+yy.toFixed(1)+"H"+(xx+bw-rr).toFixed(1)+"Q"+(xx+bw).toFixed(1)+","+yy.toFixed(1)+" "+(xx+bw).toFixed(1)+","+(yy+rr).toFixed(1)+"V"+y0+"Z";
  let s='<svg viewBox="0 0 '+W+" "+H+'" width="'+W+'" height="'+H+'" aria-hidden="true">';
  for(let v=0;v<=ymax;v+=stepv)s+='<line x1="'+ml+'" x2="'+(ml+iw)+'" y1="'+y1(v)+'" y2="'+y1(v)+'" stroke="var(--line)" stroke-width="1"/><text x="'+(ml-6)+'" y="'+(y1(v)+4)+'" text-anchor="end">'+v+"</text>";
  s+='<text x="'+ml+'" y="'+(mt-8)+'">mm</text>';
  let p1="",p2="";for(let k=0;k<d.n;k++){p1+=bar(x(k),y1(d.me.idx[k]),y1(0));if(d.pays[k]>0)p2+=bar(x(k),y2(d.pays[k]),y2(0))}
  s+='<path d="'+p1+'" fill="var(--water)"/>';
  [["hi_trig",c.trig],["hi_exit",c.exit]].forEach(q=>{s+='<line x1="'+ml+'" x2="'+(ml+iw)+'" y1="'+y1(q[1])+'" y2="'+y1(q[1])+'" stroke="var(--ink)" stroke-width="1" stroke-dasharray="4 3"/>';
    s+=W<560?'<text class="k h" x="'+(ml+4)+'" y="'+(y1(q[1])-5)+'">'+t(q[0],{v:mm(q[1])})+"</text>":'<text class="k" x="'+(ml+iw+6)+'" y="'+(y1(q[1])+4)+'">'+t(q[0],{v:mm(q[1])})+"</text>"});
  s+='<line x1="'+ml+'" x2="'+(ml+iw)+'" y1="'+y2(0)+'" y2="'+y2(0)+'" stroke="var(--line-strong)" stroke-width="1"/><line x1="'+ml+'" x2="'+(ml+iw)+'" y1="'+y2(c.limit)+'" y2="'+y2(c.limit)+'" stroke="var(--line)" stroke-width="1"/>';
  s+='<text x="'+(ml-6)+'" y="'+(y2(0)+4)+'" text-anchor="end">0</text><text x="'+(ml-6)+'" y="'+(y2(c.limit)+4)+'" text-anchor="end">'+moneyK(c.limit).replace(/\s/g,"").replace("R$","")+'</text><text class="k" x="'+ml+'" y="'+(mt+H1+gp-12)+'">'+t("hi_pay")+" (R$)</text>";
  s+='<path d="'+p2+'" fill="var(--pay)"/>';
  const every=W<560?20:10;d.years.forEach((yr,k)=>{if(yr%every===0)s+='<text x="'+(x(k)+bw/2)+'" y="'+(H-5)+'" text-anchor="middle">'+yr+"</text>"});
  const mark=(k,strong)=>{const xx=x(k)+bw/2;return '<line x1="'+xx+'" x2="'+xx+'" y1="'+(mt-2)+'" y2="'+y2(0)+'" stroke="var(--ink)" stroke-width="'+(strong?1.5:1)+'"'+(strong?"":' stroke-opacity=".45"')+"/>"+
    (strong?'<text class="k" x="'+Math.max(ml+14,Math.min(ml+iw-14,xx))+'" y="'+(mt-6)+'" text-anchor="middle" style="fill:var(--ink)">'+d.years[k]+"</text>":"")};
  if(S.season!==null)s+=mark(S.season,true);if(hHover!==null&&hHover!==S.season)s+=mark(hHover,false);
  s+="</svg>";el.innerHTML=s;
  if(hHover!==null){const tp=document.createElement("div");tp.className="tip";tp.innerHTML="<b>"+t("hi_season")+" "+d.years[hHover]+"</b>"+t("hi_index")+" "+mm1(d.me.idx[hHover])+"<br>"+t("hi_pay")+" "+money(d.pays[hHover]);el.appendChild(tp);
    const xx=x(hHover)+bw/2;tp.style.left=Math.max(0,Math.min(W-tp.offsetWidth,xx+12>W-tp.offsetWidth?xx-tp.offsetWidth-12:xx+12))+"px";tp.style.top=(mt+6)+"px"}
  el._geo={ml,sl,n:d.n};el.setAttribute("aria-label",t("hi_title")+". "+t("hi_sub",{win:c.winL[S.lang],n:d.n}));
}
function renderHistoryStatic(){
  const d=cur();
  $("#hiWarn").innerHTML=d.sig?'<div class="note warn" style="margin-top:12px">'+IC.warn+"<span>"+t("hi_warn",{p:nf({minimumFractionDigits:3,maximumFractionDigits:3}).format(d.pval)})+"</span></div>":"";
  const A=[["hi_used",d.n,""],["hi_excl",d.c.cross?1:0,""],["hi_freq",pct(d.me.freq),"freq"],["hi_trend",mm1(d.slope10),"trend"],["hi_burn",money(d.burn),"burn"],["hi_max",money(d.mx)+" · "+d.years[d.mxk],"max"]];
  $("#hiAgg").innerHTML=A.map(a=>'<div data-k="'+a[2]+'"><dt>'+t(a[0])+"</dt><dd>"+a[1]+"</dd></div>").join("");
  let h="<tr><th>"+t("hi_season")+'</th><th class="r">'+t("hi_index")+'</th><th class="r">'+t("hi_pay")+"</th></tr>";
  d.years.forEach((y,k)=>{h+='<tr><td class="num">'+y+'</td><td class="r">'+mm1(d.me.idx[k])+'</td><td class="r">'+money(d.pays[k])+"</td></tr>"});$("#hiTable").innerHTML=h;
}
const auditHtml=()=>'<ol class="audit">'+S.audit.map(a=>"<li><time>"+a[0]+'</time><span class="ac">'+a[1]+"</span><span>"+t(a[2],a[3])+"</span></li>").join("")+"</ol>";
function renderQuote(){
  const d=cur(),c=d.c,st=qStatus();if(!st){$("#quote").innerHTML='<p class="empty">'+t("q_none")+"</p>";return}
  const pc={draft:"",pending:"pending",approved:"pending",submitted:"ok",rejected:"bad"}[st],row=(k,l,v)=>'<div data-k="'+k+'"><dt>'+t(l)+"</dt><dd>"+v+"</dd></div>";
  $("#quote").innerHTML='<div class="qh"><h3 class="num">'+d.q+'</h3><span class="state '+pc+'">'+(st==="submitted"?IC.check:"")+t("st_"+st)+"</span></div>"+
    '<dl class="prem"><div data-k="prem"><dt>'+t("q_prem")+"</dt><dd>"+money(d.sim.prem)+'</dd></div><div class="rol" data-k="rol"><dt>'+t("q_rol")+"</dt><dd>"+pct(d.sim.rol,2)+"</dd></div></dl>"+
    '<h4 class="sub">'+t("q_sim")+'</h4><dl class="kv">'+row("el","q_el",money(d.sim.el))+row("","q_sd",money(d.sim.sd))+row("","q_pany",pct(d.sim.pany))+row("q10","q_q10",money(d.sim.q10))+row("q100","q_q100",money(d.sim.q100))+row("","q_gap",money(d.sim.gap))+"</dl>"+
    '<h4 class="sub">'+t("q_def")+'</h4><dl class="kv">'+row("","q_loc",c.place+" · "+ll(c.farm[0],c.farm[1]))+row("","q_ds","cube:"+c.id)+row("","q_idx","rainfall_below")+row("","q_win",c.winL[S.lang])+row("trig","q_trig",mm(c.trig))+row("exit","q_exit",mm(c.exit))+row("","q_lim",money(c.limit))+"</dl>"+
    '<h4 class="sub">'+t("q_as")+'</h4><ul class="plain"><li>'+t("as1",{win:c.winL[S.lang]})+"</li><li>"+t("as2",{n:d.n,x:c.cross?1:0})+"</li><li>"+t("as3")+"</li><li>"+t("as4")+"</li><li>"+t("as5",{w:t(d.sig?"yes":"no")})+"</li></ul>"+
    '<h4 class="sub">'+t("q_files")+'</h4><div class="dl"><button type="button" class="btn ghost" data-file="1"'+(S.step<5?" disabled":"")+">"+t("f_ts")+'</button><button type="button" class="btn ghost" data-file="1">'+t("f_nc")+'</button></div><p id="fileNote" class="fnote" hidden>'+t("f_na")+"</p>"+
    '<h4 class="sub">'+t("q_audit")+"</h4>"+auditHtml();
}
function renderApprovals(){
  const d=cur(),pend=S.step===6&&(S.appr==="none"||S.appr==="pending");$("#apBadge").hidden=!pend;
  if(S.step<6){$("#appr").innerHTML='<p class="empty">'+t("ap_empty")+"</p>";return}
  const st=qStatus(),pc={pending:"pending",approved:"pending",submitted:"ok",rejected:"bad"}[st];
  let h='<div class="apr"><div class="topl"><button type="button" class="qtag" data-go="quote">'+d.q+'</button><span class="state '+pc+'">'+t("st_"+st)+'</span><span class="sid num">'+d.s+'</span></div><dl class="kv">'+
    "<div><dt>"+t("ap_car")+"</dt><dd>"+CARRIER+"</dd></div><div><dt>"+t("q_loc")+"</dt><dd>"+d.c.place+"</dd></div><div><dt>"+t("q_lim")+"</dt><dd>"+money(d.c.limit)+"</dd></div><div><dt>"+t("ap_prem")+"</dt><dd>"+money(d.sim.prem)+"</dd></div></dl>";
  if(pend)h+='<p class="note wait">'+IC.clock+"<span>"+t("ap_you")+'</span></p><div><label for="apNote">'+t("ap_note")+'</label><textarea id="apNote"></textarea></div><div class="acts"><button type="button" class="btn go" data-dec="ok">'+t("ap_ok")+'</button><button type="button" class="btn no" data-dec="no">'+t("ap_no")+"</button></div>";
  else if(st==="approved")h+='<p class="note wait"><span class="spin"></span><span>'+t("ap_deliv")+"</span></p>";
  else if(st==="submitted")h+='<p class="note ok">'+IC.check+"<span>"+t("n_done",{r:d.rc})+"</span></p>";
  else h+='<p class="note warn">'+IC.warn+"<span>"+t("n_rej")+"</span></p>";
  $("#appr").innerHTML=h+'<h4 class="sub" style="margin:4px 0 0">'+t("q_audit")+"</h4>"+auditHtml()+"</div>";
}
function renderLanding(){
  $("#lLegs").innerHTML=[1,2,3,4,5,6].map(k=>"<li><b>"+k+"</b><strong>"+t("c"+k)+"</strong><span>"+t("lc"+k)+"</span></li>").join("");
  $("#lProof").innerHTML=[1,2,3,4].map(k=>"<div><dt>"+t("lp"+k+"t")+"</dt><dd>"+t("lp"+k)+"</dd></div>").join("");
  $("#lSpec").innerHTML=["src","var","yrs","grid","read"].map(k=>"<tr><th>"+t("sp_"+k)+"</th><td>"+(k==="read"?'<span class="tbd">'+t("sp_readv")+"</span>":t("sp_"+k+"v"))+"</td></tr>").join("");
  $("#lLimits").innerHTML=[1,2,3,4].map(k=>"<li>"+t("ll"+k)+"</li>").join("");
  $("#lStack").innerHTML=["Python","FastAPI","xarray","Zarr","Firestore","Cloud Run","Terraform","React","TypeScript","Leaflet","Inspect"].map(x=>"<span>"+x+"</span>").join("");
}

let mapA,mapL;
function drawMaps(){if(S.view==="app")mapA.draw();else mapL.draw()}
function renderData(){renderRisk();renderTimeline("A");renderTimeline("L");drawMaps();if(S.view==="app"&&S.tab==="history")renderHistory()}
function renderFlow(){renderSteps();renderChat();renderQuote();renderApprovals()}
function renderAll(){
  const st=$("#view-app"),ld=$("#view-landing");st.dataset.dir=ld.dataset.dir=S.dir;st.classList.toggle("wide",S.tab!=="risk");
  st.hidden=S.view!=="app";ld.hidden=S.view!=="landing";$("#pvState").hidden=S.view!=="app";$("#selRegion").value=S.region;
  applyText();press("segDir",S.dir);press("segView",S.view);press("segState",S.pstate);press("segLang",S.lang);press("segLang2",S.lang);press("segMetric",S.metric==="anom"&&S.season!==null?"anom":"freq");press("segBase",S.base);press("segRender",S.render);
  $$("#tabs button").forEach(b=>{const on=b.dataset.tab===S.tab;b.setAttribute("aria-selected",String(on));b.tabIndex=on?0:-1;$("#tp-"+b.dataset.tab).hidden=!on});
  renderFlow();renderHistoryStatic();renderLanding();renderData();
}

/* season most evenly split between dry and wet cells: the clearest picture of basis risk */
function contrastSeason(d){if(d.vk===undefined){let bs=-1;d.vk=0;for(let k=0;k<d.n;k++){let dry=0,wet=0;for(const c of d.cells){const v=(c.idx[k]-c.med)/c.med;if(v<-.12)dry++;else if(v>.12)wet++}const q=Math.min(dry,wet);if(q>bs){bs=q;d.vk=k}}}return d.vk}

/* ---------- actions ---------- */
function setTab(x,flash){S.tab=x;renderAll();if(flash){const e=$('#tp-'+x+' [data-k="'+flash+'"]');if(e){e.classList.add("flash");e.scrollIntoView({block:"nearest"});setTimeout(()=>e.classList.remove("flash"),1500)}}}
function setSeason(k){S.season=k;S.metric=k===null?"freq":"anom";press("segMetric",S.metric);renderData()}
function resetFlow(step){S.token++;S.step=step;S.run=0;S.ext=false;S.appr="none";seedAudit()}
async function playTo(target){const tk=++S.token;for(let k=S.step+1;k<=target;k++){S.run=k;renderFlow();await sleep(k===2?900:620);if(tk!==S.token)return;S.step=k;S.run=0;
    if(k===4)S.audit.push([now(),"agent","au_q",{}]);if(k===5)S.audit.push([now(),"agent","au_ts",{}]);if(k===6){S.audit.push([now(),"agent","au_sub",{s:cur().s,c:CARRIER}]);S.appr="pending"}
    renderFlow();if(k===3||k===4)await sleep(500);if(tk!==S.token)return}}
async function decide(ok){const d=cur(),n=($("#apNote")&&$("#apNote").value.trim())||t("no_note"),tk=S.token;
  if(!ok){S.appr="rejected";S.audit.push([now(),"human","au_no",{n}]);renderFlow();return}
  S.appr="approved";S.audit.push([now(),"human","au_ok",{n}]);renderFlow();await sleep(900);if(tk!==S.token)return;
  S.audit.push([now(),"system","au_w1",{}]);renderFlow();await sleep(1300);if(tk!==S.token)return;
  S.audit.push([now(),"system","au_w2",{}]);S.audit.push([now(),"carrier","au_rc",{r:d.rc}]);S.appr="submitted";renderFlow()}
function setView(v,push){S.view=v;if(push){try{history.replaceState(null,"","#"+v)}catch(e){}}renderAll();if(push)window.scrollTo(0,0)}
function later(){if(document.fonts&&document.fonts.ready)document.fonts.ready.then(drawMaps);setTimeout(drawMaps,700)}

document.addEventListener("click",e=>{
  const b=e.target.closest("button");if(!b)return;const seg=b.parentElement&&b.parentElement.id;
  if(seg==="segDir"){S.dir=b.dataset.v;S.base=DIR[S.dir].base;store.set("vr-dir",S.dir);renderAll();return later()}
  if(seg==="segView")return setView(b.dataset.v,true);
  if(seg==="segState"){S.pstate=b.dataset.v;return renderAll()}
  if(seg==="segLang"||seg==="segLang2"){S.lang=b.dataset.v;store.set("vr-lang",S.lang);return renderAll()}
  if(seg==="segMetric"){if(b.dataset.v==="anom")return setSeason(S.season===null?contrastSeason(cur()):S.season);return setSeason(null)}
  if(seg==="segBase"){S.base=b.dataset.v;press("segBase",S.base);return renderData()}
  if(seg==="segRender"){S.render=b.dataset.v;press("segRender",S.render);return drawMaps()}
  if(b.dataset.tab)return setTab(b.dataset.tab);
  if(b.id==="btnAll"||b.id==="btnAllL")return setSeason(null);
  if(b.id==="btnRestart"){resetFlow(0);return renderFlow()}
  if(b.id==="btnOpen")return setView("app",true);
  if(b.id==="btnSrc"){b.textContent=t("l_src_na");b.disabled=true;return}
  if(b.dataset.ex){S.region=b.dataset.ex;S.season=null;S.metric="freq";resetFlow(0);renderAll();return playTo(4)}
  if(b.dataset.act==="ext"){S.ext=true;return renderFlow()}
  if(b.dataset.act==="next")return playTo(S.step+1);
  if(b.dataset.act==="replay"){S.pstate="normal";resetFlow(0);renderAll();return playTo(6)}
  if(b.dataset.season){if(S.tab!=="risk"){S.tab="risk";renderAll()}return setSeason(+b.dataset.season)}
  if(b.dataset.go)return setTab(b.dataset.go,b.dataset.k);
  if(b.dataset.dec)return decide(b.dataset.dec==="ok");
  if(b.dataset.file){const n=$("#fileNote");if(n)n.hidden=false}
});
$("#comp").addEventListener("submit",e=>{e.preventDefault();if(S.run)return;if(S.step===0)playTo(4);else if(S.step<6)playTo(S.step+1)});
$("#selRegion").addEventListener("change",e=>{S.region=e.target.value;S.season=null;S.metric="freq";resetFlow(4);renderAll()});
["A","L"].forEach(s=>{const w=$("#tl"+s),pick=e=>{const g=$(".tl",w)._geo;if(!g)return;const x=e.clientX-w.getBoundingClientRect().left;setSeason(Math.max(0,Math.min(g.n-1,Math.floor(x/g.sl))))};
  w.addEventListener("pointerdown",e=>{try{w.setPointerCapture(e.pointerId)}catch(_){}pick(e)});w.addEventListener("pointermove",e=>{if(e.buttons)pick(e)});
  $("#rng"+s).addEventListener("input",e=>setSeason(+e.target.value))});
$("#tabs").addEventListener("keydown",e=>{if(e.key!=="ArrowRight"&&e.key!=="ArrowLeft")return;const T=["risk","history","quote","approvals"],k=(T.indexOf(S.tab)+(e.key==="ArrowRight"?1:3))%4;setTab(T[k]);$("#tab-"+T[k]).focus()});
const hist=$("#hist");
function hIdx(e){const g=hist._geo;if(!g)return null;const x=e.clientX-hist.getBoundingClientRect().left,k=Math.floor((x-g.ml)/g.sl);return k>=0&&k<g.n?k:null}
hist.addEventListener("pointermove",e=>{const k=hIdx(e);if(k!==hHover){hHover=k;renderHistory()}});
hist.addEventListener("pointerleave",()=>{if(hHover!==null){hHover=null;renderHistory()}});
hist.addEventListener("click",e=>{const k=hIdx(e);if(k!==null)setSeason(k)});
hist.addEventListener("keydown",e=>{if(e.key!=="ArrowRight"&&e.key!=="ArrowLeft")return;e.preventDefault();const d=cur(),k=S.season===null?d.n-1:S.season;setSeason(Math.max(0,Math.min(d.n-1,k+(e.key==="ArrowRight"?1:-1))))});

mapA=MapView($("#mapA"),padApp);mapL=MapView($("#mapL"),padLand);
const route=()=>{const h=(location.hash||"").replace("#","");if(h==="landing"||h==="app")S.view=h;renderAll()};
window.addEventListener("hashchange",()=>{const h=(location.hash||"").replace("#","");if(h==="landing"||h==="app")route()});
seedAudit();route();later();
let rz;window.addEventListener("resize",()=>{clearTimeout(rz);rz=setTimeout(renderData,80)});
})();
