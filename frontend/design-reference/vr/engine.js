(function(){"use strict";
/* ---------- regions (synthetic scenarios) ---------- */
const REG={
 mg:{name:"Sul de Minas (MG)",id:"sul-de-minas",north:-20.4,west:-46.6,place:"Três Pontas, MG",farm:[-21.41,-45.48],win:["09-01","10-31"],winL:{en:"1 Sep to 31 Oct",pt:"1º set a 31 out"},mean:215,trig:150,exit:75,limit:30000000,trend:-0.04,seed:1107,cross:false,
  u:{en:"Coffee farm near Três Pontas, MG. The client worries about a dry spell during flowering, 1 Sep to 31 Oct. Pay when rainfall is below 150 mm, in full at 75 mm. Limit R$ 300,000.",pt:"Fazenda de café perto de Três Pontas, MG. O cliente teme um veranico na florada, de 1º de setembro a 31 de outubro. Pagar quando a chuva ficar abaixo de 150 mm, integral em 75 mm. Limite de R$ 300.000."},
  ex:{en:"Coffee · Sul de Minas",pt:"Café · Sul de Minas"},towns:[["Três Pontas",-21.37,-45.51],["Varginha",-21.55,-45.43],["Alfenas",-21.43,-45.95],["Lavras",-21.25,-45.0],["Boa Esperança",-21.09,-45.57],["Poços de Caldas",-21.79,-46.5]]},
 mt:{name:"Sorriso (MT)",id:"sorriso",north:-11.5,west:-56.7,place:"Sorriso, MT",farm:[-12.6,-55.66],win:["10-01","11-30"],winL:{en:"1 Oct to 30 Nov",pt:"1º out a 30 nov"},mean:385,trig:280,exit:160,limit:50000000,trend:0,seed:2214,cross:false,
  u:{en:"Soybean farm near Sorriso, MT. The risk is a dry start after planting, 1 Oct to 30 Nov. Pay below 280 mm, in full at 160 mm. Limit R$ 500,000.",pt:"Fazenda de soja perto de Sorriso, MT. O risco é faltar chuva depois do plantio, de 1º de outubro a 30 de novembro. Pagar abaixo de 280 mm, integral em 160 mm. Limite de R$ 500.000."},
  ex:{en:"Soybean · Sorriso",pt:"Soja · Sorriso"},towns:[["Sorriso",-12.55,-55.72],["Lucas do Rio Verde",-13.07,-55.92],["Sinop",-11.86,-55.51],["Vera",-12.3,-55.31],["Ipiranga do Norte",-12.24,-56.15]]},
 sp:{name:"Ribeirão Preto (SP)",id:"ribeirao-preto",north:-20.2,west:-48.8,place:"Sertãozinho, SP",farm:[-21.1,-48.03],win:["11-15","02-15"],winL:{en:"15 Nov to 15 Feb",pt:"15 nov a 15 fev"},mean:720,trig:520,exit:330,limit:40000000,trend:0,seed:3391,cross:true,
  u:{en:"Sugarcane near Sertãozinho, SP. The concern is a dry summer, 15 Nov to 15 Feb. Pay below 520 mm, in full at 330 mm. Limit R$ 400,000.",pt:"Cana-de-açúcar perto de Sertãozinho, SP. A preocupação é um verão seco, de 15 de novembro a 15 de fevereiro. Pagar abaixo de 520 mm, integral em 330 mm. Limite de R$ 400.000."},
  ex:{en:"Sugarcane · Ribeirão Preto",pt:"Cana · Ribeirão Preto"},towns:[["Ribeirão Preto",-21.18,-47.81],["Sertãozinho",-21.14,-47.99],["Jaboticabal",-21.25,-48.32],["Batatais",-20.89,-47.59],["Franca",-20.54,-47.4],["Araraquara",-21.79,-48.18],["São Carlos",-22.02,-47.89]]}
};
const N=20, CARRIER="Aurora Re (mock)";

/* ---------- numerics ---------- */
function rng(seed){let a=seed>>>0;return()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
function gauss(r){let u=0;while(u===0)u=r();return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*r())}
function field(r,n,fq){const k=[];for(let i=0;i<n;i++)k.push([(r()*2-1)*fq*6.283,(r()*2-1)*fq*6.283,r()*6.283]);return(x,y)=>{let s=0;for(const q of k)s+=Math.sin(q[0]*x+q[1]*y+q[2]);return s/n}}
function phi(z){const t=1/(1+0.2316419*Math.abs(z)),d=0.3989423*Math.exp(-z*z/2);const p=d*t*(0.3193815+t*(-0.3565638+t*(1.781478+t*(-1.821256+t*1.330274))));return z>0?1-p:p}
function gammaS(k,th,r){const d=k-1/3,c=1/Math.sqrt(9*d);for(;;){let x,v;do{x=gauss(r);v=1+c*x}while(v<=0);v=v*v*v;const u=r();if(u<1-0.0331*x*x*x*x||Math.log(u)<0.5*x*x+d*(1-v+Math.log(v)))return d*v*th}}
function km(a,b){const R=6371,p=Math.PI/180,dl=(b[0]-a[0])*p,dn=(b[1]-a[1])*p;const h=Math.sin(dl/2)**2+Math.cos(a[0]*p)*Math.cos(b[0]*p)*Math.sin(dn/2)**2;return 2*R*Math.asin(Math.sqrt(h))}
function hashId(seed,pre){let h=(seed*2654435761)>>>0,s="";const A="23456789ABCDEFGHJKMNPQRSTVWXYZ";for(let i=0;i<6;i++){s+=A[h%A.length];h=Math.floor(h/A.length)+(i+1)*7919}return pre+"-"+s}

const cache={};
function build(id){
  const c=REG[id],r=rng(c.seed),years=[];
  for(let y=1950;y<=2024-(c.cross?1:0);y++)years.push(y);
  const n=years.length,big=field(r,3,.55),fine=field(r,3,2.1);
  const reg=years.map(y=>Math.max(-.5,Math.min(.55,0.2*gauss(r)))+c.trend*((y-1987)/10));
  const yf=years.map(()=>field(r,2,1.3));
  const h=(x,y)=>0.62*big(x,y)+0.38*fine(x,y);
  const cells=[];
  for(let j=0;j<N;j++)for(let i=0;i<N;i++){
    const x=(i+.5)/N,y=(j+.5)/N,base=c.mean*(1+0.19*big(x,y)+0.12*fine(x,y)),idx=new Float64Array(n);
    for(let k=0;k<n;k++)idx[k]=Math.round(Math.max(0,base*(1+reg[k])*(1+0.26*yf[k](x,y)+0.05*gauss(r)))*10)/10;
    const srt=Float64Array.from(idx).sort(),med=srt[n>>1];let f=0;for(let k=0;k<n;k++)if(idx[k]<c.trig)f++;
    cells.push({i,j,idx,med,freq:f/n,lat:c.north-(j+.5)*.1,lon:c.west+(i+.5)*.1});
  }
  const fi=Math.floor((c.farm[1]-c.west)/.1),fj=Math.floor((c.north-c.farm[0])/.1),me=cells[fj*N+fi];
  const pay=v=>Math.round(c.limit*Math.min(1,Math.max(0,(c.trig-v)/(c.trig-c.exit))));
  const pays=Array.from(me.idx,pay);
  let sum=0,mx=0,mxk=0,cnt=0;pays.forEach((p,k)=>{sum+=p;if(p>0)cnt++;if(p>mx){mx=p;mxk=k}});
  const burn=Math.round(sum/n);
  // season in which the cells around the farm disagree most with the insured cell
  let bk=0,bs=-1;for(let k=0;k<n;k++){const mt=me.idx[k]<c.trig;let o=0;for(let dj=-3;dj<=3;dj++)for(let di=-3;di<=3;di++){const ci=fi+di,cj=fj+dj;if(ci<0||cj<0||ci>=N||cj>=N)continue;if((cells[cj*N+ci].idx[k]<c.trig)!==mt)o++}if(o>bs){bs=o;bk=k}}
  const paid=years.map((y,k)=>{let q=0;for(const cl of cells)if(cl.idx[k]<c.trig)q++;return q});
  // linear trend of the index
  const xm=years.reduce((a,b)=>a+b,0)/n,ym=me.idx.reduce((a,b)=>a+b,0)/n;let sxx=0,sxy=0;
  for(let k=0;k<n;k++){sxx+=(years[k]-xm)**2;sxy+=(years[k]-xm)*(me.idx[k]-ym)}
  const slope=sxy/sxx;let sse=0;for(let k=0;k<n;k++)sse+=(me.idx[k]-(ym+slope*(years[k]-xm)))**2;
  const se=Math.sqrt(sse/(n-2)/sxx),pval=2*(1-phi(Math.abs(slope/se)));
  // simulation: gamma by moments, 100,000 seasons, seed 42
  let vr=0;for(let k=0;k<n;k++)vr+=(me.idx[k]-ym)**2;vr/=(n-1);
  const kk=ym*ym/vr,th=vr/ym,rs=rng(42),M=100000,sp=new Float64Array(M);let s1=0,s2=0,any=0;
  for(let m=0;m<M;m++){const p=c.limit*Math.min(1,Math.max(0,(c.trig-gammaS(kk,th,rs))/(c.trig-c.exit)));sp[m]=p;s1+=p;s2+=p*p;if(p>0)any++}
  sp.sort();const el=s1/M,sd=Math.sqrt(Math.max(0,s2/M-el*el)),prem=el+0.3*sd+0.15*el;
  const order=years.map((y,k)=>k).sort((a,b)=>me.idx[a]-me.idx[b]);
  const ext=order.slice(0,3).map((k,rk)=>({k,rp:Math.round((n+1)/(rk+1))}));
  const nb=[];const DD=[[0,-1],[1,-1],[1,0],[1,1],[0,1],[-1,1],[-1,0],[-1,-1]];
  DD.forEach((d,q)=>{const ci=fi+d[0],cj=fj+d[1];if(ci>=0&&cj>=0&&ci<N&&cj<N){const cl=cells[cj*N+ci];nb.push({dir:q,cell:cl,d:km(c.farm,[cl.lat,cl.lon])})}});
  // widest contrast within two cells, for the landing caption
  let far=null;for(let dj=-2;dj<=2;dj++)for(let di=-2;di<=2;di++){if(!di&&!dj)continue;const ci=fi+di,cj=fj+dj;if(ci<0||cj<0||ci>=N||cj>=N)continue;const cl=cells[cj*N+ci];
    if(!far||Math.abs(cl.freq-me.freq)>Math.abs(far.cell.freq-me.freq)){const ang=(Math.atan2(di,-dj)*180/Math.PI+360)%360;far={cell:cl,d:km(c.farm,[cl.lat,cl.lon]),dir:Math.round(ang/45)%8}}}
  // contour segments of the terrain field
  const G=56,hv=[];for(let b=0;b<=G;b++){hv.push([]);for(let a=0;a<=G;a++)hv[b].push(h(a/G,b/G))}
  const segs=[];[-.6,-.42,-.24,-.06,.12,.3,.48].forEach((L,li)=>{for(let b=0;b<G;b++)for(let a=0;a<G;a++){
    const v=[hv[b][a],hv[b][a+1],hv[b+1][a+1],hv[b+1][a]],P=[[a,b],[a+1,b],[a+1,b+1],[a,b+1]],pt=[];
    for(let e=0;e<4;e++){const v1=v[e],v2=v[(e+1)%4];if((v1<L)!==(v2<L)){const t=(L-v1)/(v2-v1),p1=P[e],p2=P[(e+1)%4];pt.push([(p1[0]+t*(p2[0]-p1[0]))/G,(p1[1]+t*(p2[1]-p1[1]))/G])}}
    if(pt.length>=2)segs.push([pt[0],pt[1],li]);if(pt.length===4)segs.push([pt[2],pt[3],li])}});
  const ph=r()*6.28,river=[];for(let s=0;s<=40;s++){const t=s/40;river.push([t,.34+.22*Math.sin(3.1*t+ph)+.04*Math.sin(11*t)])}
  const towns=c.towns.map(tn=>({name:tn[0],x:(tn[2]-c.west)/2,y:(c.north-tn[1])/2}));
  return {c,id,years,n,cells,me,fi,fj,pay,pays,bk,paid,burn,cnt,mx,mxk,slope10:slope*10,pval,sig:pval<0.05,
    sim:{el:Math.round(el),sd:Math.round(sd),pany:any/M,q10:Math.round(sp[Math.floor(.9*M)]),q100:Math.round(sp[Math.floor(.99*M)]),gap:Math.round(el)-burn,prem:Math.round(prem),rol:prem/c.limit},
    ext,nb,far,segs,river,towns,h,fx:(c.farm[1]-c.west)/2,fy:(c.north-c.farm[0])/2,q:hashId(c.seed,"Q"),s:hashId(c.seed+7,"S"),rc:hashId(c.seed+13,"R"),sat:{}};
}



window.VR={REG,N,CARRIER,km,build:id=>cache[id]||(cache[id]=build(id))};
})();
