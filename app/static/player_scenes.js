/* Bounded presentation helpers. No audio ownership, timers, or animation loops. */
(() => {
  const TAU = Math.PI * 2, clamp = (v, a=0, b=1) => Math.max(a, Math.min(b, v));
  const mix = (a,b,t) => a+(b-a)*t, ease = t => {t=clamp(t);return t*t*(3-2*t);};
  const formations = ['galaxy','vortex','torus','ribbons','constellation'];
  const geometry = ['mandala','polyhedra','lattice','ribbons'];
  const visits = [
    {family:0, x:-.743643887, y:.131825904, cr:0, ci:0, zoom:7.3},
    {family:1, x:0, y:0, cr:-.8, ci:.156, zoom:3.8},
    {family:1, x:.06, y:.04, cr:-.7269, ci:.1889, zoom:4.5},
    {family:0, x:-.16, y:1.035, cr:0, ci:0, zoom:5.4},
    {family:1, x:0, y:0, cr:-.4, ci:.6, zoom:3.6}
  ];
  // Presentation-only onset/tempo tracker; no timer or audio graph ownership.
  function createTempo() {
    let previous=new Float32Array(64),mean=0,variance=0,time=0,last=-1,age=0,bpm=0,pulse=0,intervals=[],onsets=0;
    return {sample(data,dt,active) {
      if(!active){previous.fill(0);mean=variance=0;last=-1;age=0;bpm=0;pulse=0;intervals=[];return {bpm:0,pulse:0,onsets};}
      if(dt<=0)return {bpm,pulse,onsets};
      time+=dt;age+=dt;pulse*=Math.exp(-dt*6);
      let flux=0,level=0;
      for(let i=1;i<64;i++){const value=data[i]/255;flux+=Math.max(0,value-previous[i]);level+=value;previous[i]=value;}
      flux/=63;const delta=flux-mean;
      const onset=age>.4 && level>.3 && flux>.009 && delta>Math.max(.008,Math.sqrt(variance)*1.4) && (last<0 || time-last>.28);
      const blend=1-Math.exp(-dt*2);mean+=delta*blend;variance+=(delta*delta-variance)*blend;
      if(onset){
        if(last>=0){let interval=time-last;
          if(bpm && interval>1.1)interval/=Math.max(1,Math.round(interval*bpm/60));
          if(interval>=.28 && interval<=1.03){intervals.push(interval);if(intervals.length>8)intervals.shift();
            if(intervals.length>=3){const sorted=[...intervals].sort((a,b)=>a-b),median=sorted[Math.floor(sorted.length/2)];
              const stable=sorted.filter(v=>Math.abs(v-median)<median*.18);
              if(stable.length>=3){const target=clamp(60/(stable.reduce((a,b)=>a+b,0)/stable.length),60,180);bpm=bpm?mix(bpm,target,.25):target;}}
          }
        }
        last=time;pulse=1;onsets++;
      }
      if(last>=0 && time-last>4){bpm=0;intervals=[];}
      return {bpm,pulse,onsets};
    }};
  }
  window.FreoVisualScenes = {createTempo,create(canvas, ctx, scope) {
    const dots = Array.from({length:420},(_,i)=>({u:(i+.5)/420, a:i*2.399963, seed:((i*137+31)%421)/421, size:1+i%4, x:0,y:0,z:0,px:0,py:0}));
    const rocks = Array.from({length:72},(_,i)=>({a:i*2.399963,r:.32+(i%13)/20,z:(i%9)/9,size:1+i%5,spin:i*.71}));
    let view, glState=null, gpuTried=false, gpuDisabled=false, disposed=false;
    let slowGPU=0, gpuDraws=0, gpuMean=0, raster=null, rasterContext=null, rasterData=null, rasterTime=-Infinity, rasterHue=-1;
    let quality=1, cost=0, frames=0, lastMode='', particleReady=false;
    const qualities = Object.create(null);
    let bassFloor=0, pulse=0, onsetAt=-1, audioTime=0;
    const white=(alpha=1)=>`rgba(238,247,255,${clamp(alpha)})`;
    const stroke=(points,style,width=1,close=false)=>{
      ctx.beginPath();for(let i=0;i<points.length;i++){const p=points[i];if(i)ctx.lineTo(p[0],p[1]);else ctx.moveTo(p[0],p[1]);}
      if(close)ctx.closePath();ctx.strokeStyle=style;ctx.lineWidth=width;ctx.stroke();
    };
    const project=(x,y,z,scale=1)=>{
      const yaw=view.time*.12, tilt=.28+Math.sin(view.time*.08)*.16;
      const rx=x*Math.cos(yaw)+z*Math.sin(yaw), rz=z*Math.cos(yaw)-x*Math.sin(yaw);
      const ry=y*Math.cos(tilt)-rz*Math.sin(tilt), depth=y*Math.sin(tilt)+rz*Math.cos(tilt);
      const perspective=2.7/(2.7-depth);
      return [view.w*.5+rx*view.unit*scale*perspective,view.h*.52+ry*view.unit*scale*perspective,perspective,depth];
    };
    function discardGPU() {
      const state=glState;glState=null;
      if(!state)return;
      try {state.gl.deleteBuffer(state.buffer);state.gl.deleteProgram(state.program);if(!state.gl.isContextLost())state.gl.getExtension('WEBGL_lose_context')?.loseContext();} catch {}
      state.surface.width=state.surface.height=1;
    }
    function initGPU() {
      if(gpuTried || gpuDisabled || disposed)return;
      gpuTried=true;
      let gl, program, buffer;
      try {
        const surface=document.createElement('canvas');
        gl=surface.getContext('webgl',{alpha:false,antialias:false,depth:false,stencil:false,preserveDrawingBuffer:false,powerPreference:'low-power'});
        if(!gl || !gl.getShaderPrecisionFormat(gl.FRAGMENT_SHADER,gl.HIGH_FLOAT)?.precision)throw Error('No fragment precision');
        scope.listen(surface,'webglcontextlost',event=>{event.preventDefault();if(!gpuDisabled){gpuDisabled=true;canvas.dataset.fractalFallbackReason='context-lost';}canvas.dataset.fractalRenderer='canvas';discardGPU();});
        const compile=(type,source)=>{
          const shader=gl.createShader(type);gl.shaderSource(shader,source);gl.compileShader(shader);
          if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)){gl.deleteShader(shader);throw Error('Fractal shader');}
          return shader;
        };
        const vertex=compile(gl.VERTEX_SHADER,'attribute vec2 position;void main(){gl_Position=vec4(position,0.,1.);}');
        const fragment=compile(gl.FRAGMENT_SHADER,`precision highp float;
          uniform vec2 resolution,center,julia;uniform float scale,angle,family,hue,energy,bass,mids,highs,iterations;
          vec3 palette(float t){return .5+.5*cos(6.283185*(vec3(t)+vec3(0.,.18,.37)+hue));}
          void main(){
            vec2 p=(gl_FragCoord.xy/resolution-.5)*vec2(resolution.x/resolution.y,1.)*scale;
            p=mat2(cos(angle),-sin(angle),sin(angle),cos(angle))*p+center;
            vec2 z=mix(vec2(0.),p,family),c=mix(p,julia,family);
            float count=0.,trap=10.,radius=0.;
            for(int i=0;i<96;i++){
              if(float(i)>=iterations)break;
              z=vec2(z.x*z.x-z.y*z.y,2.*z.x*z.y)+c;radius=dot(z,z);
              trap=min(trap,abs(length(z)-.55));count=float(i);
              if(radius>100.)break;
            }
            float smoothCount=count+1.-log2(max(1.,log2(max(radius,1.001))));
            vec3 tint=palette(smoothCount*.031+mids*.07);
            float inside=step(count,iterations-2.);
            vec3 inner=vec3(.015,.022,.055)+palette(trap*2.+.35)*(.04+exp(-trap*12.)*(.12+highs*.16));
            vec3 rgb=mix(inner,tint*(.5+energy*.4)+vec3(.12)*exp(-trap*18.)*bass,inside);
            float vignette=1.-.35*length((gl_FragCoord.xy/resolution-.5)*1.3);
            gl_FragColor=vec4(rgb*vignette,1.);
          }`);
        program=gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);
        gl.deleteShader(vertex);gl.deleteShader(fragment);
        if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('Fractal program');
        buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
        const names=['resolution','center','julia','scale','angle','family','hue','energy','bass','mids','highs','iterations'];
        glState={surface,gl,program,buffer,locations:Object.fromEntries(names.map(name=>[name,gl.getUniformLocation(program,name)]))};
      } catch {
        try {if(buffer)gl.deleteBuffer(buffer);if(program)gl.deleteProgram(program);gl?.getExtension('WEBGL_lose_context')?.loseContext();}catch{}
        gpuDisabled=true;canvas.dataset.fractalFallbackReason='unavailable';
      }
    }
    function fractalPass(scene,progress,opacity) {
      const {w,h,time,bass,mids,treble,energy,mobile,color}=view;
      const state=glState;if(!state || gpuDisabled || state.gl.isContextLost())return false;
      const {gl,surface,program,buffer,locations:u}=state;
      const budget=(mobile?180000:400000)*quality, ratio=Math.min(1,Math.sqrt(budget/(w*h)));
      const width=Math.max(1,Math.round(w*ratio)),height=Math.max(1,Math.round(h*ratio));
      if(surface.width!==width || surface.height!==height){surface.width=width;surface.height=height;}
      gl.viewport(0,0,width,height);gl.useProgram(program);gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
      const position=gl.getAttribLocation(program,'position');gl.enableVertexAttribArray(position);gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
      gl.uniform2f(u.resolution,width,height);gl.uniform2f(u.center,scene.x,scene.y);
      const drift=scene.family ? .008*mids : 0;
      gl.uniform2f(u.julia,scene.cr+Math.sin(time*.27)*drift,scene.ci+Math.cos(time*.21)*drift);
      gl.uniform1f(u.scale,2.9*Math.exp(-progress*scene.zoom)*(1-bass*.06));
      gl.uniform1f(u.angle,time*.045+Math.sin(time*.15)*mids*.12);gl.uniform1f(u.family,scene.family);
      gl.uniform1f(u.hue,view.hues[0]/360);gl.uniform1f(u.energy,energy);gl.uniform1f(u.bass,bass);gl.uniform1f(u.mids,mids);gl.uniform1f(u.highs,treble);
      gl.uniform1f(u.iterations,Math.floor((mobile?64:96)*Math.max(.65,quality)));
      gl.drawArrays(gl.TRIANGLES,0,6);
      if(gl.getError()!==gl.NO_ERROR)throw Error('Fractal draw');
      // Copy immediately while the non-preserved drawing buffer is valid.
      ctx.globalAlpha=opacity;ctx.drawImage(surface,0,0,w,h);ctx.globalAlpha=1;
      return true;
    }
    function canvasFractal() {
      const {w,h,time,bass,mids,treble,energy,hues,mobile}=view;
      // Same escape-time fractals at a bounded resolution/refresh rate when
      // GPU rendering is unavailable or too slow. Never substitute fake audio.
      raster ||= document.createElement('canvas');
      rasterContext ||= raster.getContext('2d');
      const width=Math.round((mobile?112:160)*Math.sqrt(quality)),height=Math.max(16,Math.round(width*h/w));
      const boundedHeight=Math.min(110,height);
      if(raster.width!==width || raster.height!==boundedHeight){raster.width=width;raster.height=boundedHeight;rasterData=rasterContext.createImageData(width,boundedHeight);rasterTime=-Infinity;}
      if(Math.abs(time-rasterTime)>.12 || rasterHue!==hues[0]){
        rasterTime=time;rasterHue=hues[0];
        const visit=time/20,index=Math.floor(visit)%visits.length,p=visit%1,progress=clamp(p+Math.sin(p*Math.PI)*bass*.08),blend=ease((p-.8)/.2);
        const scene=visits[index],next=visits[(index+1)%visits.length];
        const colors=new Float32Array(384);
        for(let i=0;i<128;i++)for(let channel=0;channel<3;channel++)colors[i*3+channel]=.5+.5*Math.cos(TAU*(i/128+[0,.18,.37][channel]+hues[0]/360));
        const angle=time*.045+Math.sin(time*.15)*mids*.12,cos=Math.cos(angle),sin=Math.sin(angle);
        const setup=(scene,progress)=>({...scene,scale:2.9*Math.exp(-progress*scene.zoom)*(1-bass*.06),
          cr:scene.cr+Math.sin(time*.27)*.008*mids,ci:scene.ci+Math.cos(time*.21)*.008*mids});
        const firstScene=setup(scene,progress),nextScene=setup(next,0),limit=mobile?28:44;
        const escape=(scene,px,py)=>{
          const xx=(px/width-.5)*(w/h)*scene.scale,yy=(.5-py/boundedHeight)*scene.scale;
          const x=xx*cos-yy*sin+scene.x,y=xx*sin+yy*cos+scene.y;
          const cr=scene.family?scene.cr:x,ci=scene.family?scene.ci:y;
          let zx=scene.family?x:0,zy=scene.family?y:0,trap=10,radius=0,n=0;
          for(;n<limit;n++){const nx=zx*zx-zy*zy+cr;zy=2*zx*zy+ci;zx=nx;radius=zx*zx+zy*zy;trap=Math.min(trap,Math.abs(radius-.3025));if(radius>100)break;}
          let red,green,blue;
          if(n===limit){const glow=Math.exp(-trap*12);red=.025+glow*.13;green=.035+glow*.16;blue=.07+glow*.2;}
          else {
            const smooth=n+1-Math.log2(Math.max(1,Math.log2(Math.max(radius,1.001))));
            const index=(((Math.floor((smooth*.031+mids*.07)*128)%128)+128)%128)*3;
            const light=.5+energy*.4,accent=.12*Math.exp(-trap*18)*bass;
            red=colors[index]*light+accent;green=colors[index+1]*light+accent;blue=colors[index+2]*light+accent;
          }
          return (clamp(red)*255)|((clamp(green)*255)<<8)|((clamp(blue)*255)<<16);
        };
        for(let y=0;y<boundedHeight;y++)for(let x=0;x<width;x++){
          const first=escape(firstScene,x,y),second=blend?escape(nextScene,x,y):first,k=(y*width+x)*4;
          const vignette=1-.35*Math.hypot((x/width-.5)*1.3,(y/boundedHeight-.5)*1.3);
          for(let channel=0;channel<3;channel++)rasterData.data[k+channel]=mix((first>>channel*8)&255,(second>>channel*8)&255,blend)*vignette;
          rasterData.data[k+3]=255;
        }
        rasterContext.putImageData(rasterData,0,0);
      }
      ctx.imageSmoothingEnabled=true;ctx.drawImage(raster,0,0,w,h);
    }
    function fractal() {
      initGPU();canvas.dataset.fractalRenderer=glState && !gpuDisabled?'webgl':'canvas';
      const visit=view.time/20,index=Math.floor(visit)%visits.length,p=visit%1,progress=clamp(p+Math.sin(p*Math.PI)*view.bass*.08),blend=ease((p-.8)/.2);
      canvas.dataset.fractalVisit=String(index);canvas.dataset.fractalZoom=(2.9*Math.exp(-progress*visits[index].zoom)).toFixed(4);
      const started=performance.now();
      try {
        if(!fractalPass(visits[index],progress,1)){canvasFractal();return;}
        if(blend>0)fractalPass(visits[(index+1)%visits.length],0,blend);
        const duration=performance.now()-started;
        // Ignore the first draw in the mean: some drivers compile lazily.
        if(gpuDraws++)gpuMean=mix(gpuMean,duration,.3);
        if(duration>80){slowGPU++;quality=Math.max(.5,quality*.5);}else slowGPU=0;
        if(slowGPU>=2 || (gpuDraws>5 && gpuMean>40)){gpuDisabled=true;canvas.dataset.fractalFallbackReason='slow-gpu';discardGPU();canvas.dataset.fractalRenderer='canvas';}
      }catch {gpuDisabled=true;discardGPU();canvas.dataset.fractalRenderer='canvas';canvas.dataset.fractalFallbackReason='draw-error';canvasFractal();}
    }
    function formation(type,p,time) {
      const a=p.a+time*.22,u=p.u,r=Math.sqrt(u),s=Math.sin,c=Math.cos;
      if(type===0)return [c(a+r*7)*r*.46,s(a+r*7)*r*.23,s(a*3+r*5)*.16];
      if(type===1)return [c(a+time*.3+u*9)*(.12+r*.35),s(a+time*.3+u*9)*(.12+r*.35),(u-.5)*.7];
      if(type===2){const b=p.seed*TAU;return [c(a)*(.32+.12*c(b)),s(b)*.17,s(a)*(.32+.12*c(b))];}
      if(type===3)return [(u-.5)*1.1,s(u*TAU*2+time+p.seed*3)*.25,c(u*TAU+time*.6)*.22];
      return [c(p.a)*(.15+p.seed*.45),s(p.a)*(.15+p.seed*.4),s(p.a*1.7+time*.15)*.24];
    }
    function particles() {
      const {time,unit,bass,treble,energy,color,mobile}=view;
      const sequence=time/9,a=Math.floor(sequence)%formations.length,b=(a+1)%formations.length,t=ease((sequence%1-.55)/.45);
      const count=Math.floor((mobile?220:420)*Math.max(.6,quality));
      canvas.dataset.formation=formations[a];canvas.dataset.particleCount=String(count);
      ctx.globalCompositeOperation='screen';
      for(let i=0;i<count;i++){
        const p=dots[i];p.u=(i+.5)/count;
        const first=formation(a,p,time),second=formation(b,p,time),expand=1+bass*.3+pulse*.24;
        const pos=project(mix(first[0],second[0],t)*expand,mix(first[1],second[1],t)*expand,mix(first[2],second[2],t));
        p.px=p.x;p.py=p.y;p.x=pos[0];p.y=pos[1];p.z=pos[3];
        const size=Math.max(.7,p.size*unit/800*pos[2]*(1+treble*.9)),alpha=clamp(.36+pos[3]*.45+energy*.3,.15,.9);
        if(particleReady && Math.hypot(p.x-p.px,p.y-p.py)<unit*.25)stroke([[p.px,p.py],[p.x,p.y]],color(i,alpha*.5),size*.65);
        if(a===4 && i>2 && i%3===0){const neighbor=dots[i-3];if(Math.hypot(p.x-neighbor.x,p.y-neighbor.y)<unit*.14)stroke([[p.x,p.y],[neighbor.x,neighbor.y]],color(i,alpha*.22),.7);}
        ctx.fillStyle=i%7===0?white(alpha):color(i,alpha);ctx.beginPath();ctx.arc(p.x,p.y,size,0,TAU);ctx.fill();
        if(i%9===0){ctx.globalAlpha=.17;ctx.beginPath();ctx.arc(p.x,p.y,size*3,0,TAU);ctx.fill();ctx.globalAlpha=1;}
      }
      particleReady=true;
      if(pulse>.025){ctx.strokeStyle=white(pulse*.3);ctx.lineWidth=unit*.003;ctx.beginPath();ctx.ellipse(view.w*.5,view.h*.52,unit*(.15+(1-pulse)*.45),unit*(.09+(1-pulse)*.2),time*.12,0,TAU);ctx.stroke();}
    }
    function geometricPoint(type,t,layer,time) {
      const a=t*TAU,r=.12+layer*.035;
      if(type===0){const petal=1+.19*Math.cos(a*(5+layer%3)+time*.35);return [Math.cos(a)*r*petal,Math.sin(a)*r*petal,Math.sin(a*3+layer+time*.3)*.12];}
      if(type===1){const sides=3+layer%6,seg=t*sides,i=Math.floor(seg),f=seg-i;
        return [mix(Math.cos(i*TAU/sides),Math.cos((i+1)*TAU/sides),f)*r,mix(Math.sin(i*TAU/sides),Math.sin((i+1)*TAU/sides),f)*r,Math.sin(layer*.7+time*.25)*.24];}
      if(type===2)return [(t-.5)*1.05,(layer-6)*.05+Math.sin(t*9+time*.6+layer*.4)*.1,Math.cos(t*7-time*.4+layer*.2)*.22];
      return [Math.cos(a)*r,Math.sin(a*2+time*.2)*r,Math.sin(a+time*.25+layer*.2)*.23];
    }
    function ambient() {
      const {w,h,time,unit,bass,mids,treble,energy,color,mobile}=view;
      const seq=time/10,a=Math.floor(seq)%geometry.length,b=(a+1)%geometry.length,blend=ease((seq%1-.45)/.55);
      canvas.dataset.formation=geometry[a];
      const steps=Math.floor((mobile?56:84)*Math.max(.7,quality)),layers=Math.floor((mobile?10:14)*Math.max(.65,quality));
      ctx.globalCompositeOperation='screen';
      for(let layer=0;layer<layers;layer++){
        const points=[];
        for(let i=0;i<=steps;i++){
          const t=i/steps,p=geometricPoint(a,t,layer,time),q=geometricPoint(b,t,layer,time);
          const sweep=Math.sin(time*.9+layer*.3)*(.045+mids*.065);
          const x=mix(p[0],q[0],blend)+sweep,y=mix(p[1],q[1],blend)+Math.cos(time*.7+layer*.25)*(.02+mids*.035),z=mix(p[2],q[2],blend);
          const ripple=Math.sin(t*TAU*3-time*2-layer*.55)*(.012+mids*.035+pulse*.035);
          const expansion=1+bass*.32+pulse*.3+ripple;
          points.push(project(x*expansion,y*expansion,z+Math.sin(t*15+time*1.6)*mids*.09));
        }
        if(a!==2 && blend<.8){ctx.beginPath();for(let i=0;i<points.length;i++)i?ctx.lineTo(points[i][0],points[i][1]):ctx.moveTo(points[i][0],points[i][1]);ctx.closePath();
          const sweep=(time*.16+layer*.11)%1;
          const fill=ctx.createLinearGradient(w*(sweep-.5),h*.2,w*(sweep+.5),h*.8);
          for(let stop=0;stop<5;stop++)fill.addColorStop(stop/4,color(layer+stop,.045+energy*.09+pulse*.09));
          ctx.fillStyle=fill;ctx.fill();
          const wave=ctx.createRadialGradient(w*(.5+Math.sin(time*.65+layer)*.2),h*(.5+Math.cos(time*.7+layer)*.2),unit*.02,w*.5,h*.5,unit*(.3+pulse*.18));
          wave.addColorStop(0,color(layer+1,.025+energy*.1));wave.addColorStop(.45,color(layer+2,.025+pulse*.12));wave.addColorStop(1,color(layer,0));
          ctx.fillStyle=wave;ctx.fill();}
        stroke(points,color(layer,.24+mids*.35),Math.max(.8,unit/900)*(1+pulse*.7));
        if(layer%3===0)stroke(points,white(.1+treble*.23),Math.max(.6,unit/1400));
        if(layer && a===1){const p=points[layer*5%steps],q=project(0,0,(layer-6)*.035);stroke([p,q],color(layer,.15+treble*.15),.8);}
      }
    }
    function ethereal() {
      const {w,h,unit,time,bass,mids,treble,energy,color,mobile}=view;
      ctx.globalCompositeOperation='screen';
      const ox=w*(.5+Math.sin(time*.17)*.23),oy=h*(-.08+Math.sin(time*.11)*.07);
      const fans=mobile?[6,4]:[8,6];
      for(let fan=0;fan<2;fan++)for(let ray=0;ray<fans[fan];ray++){
        const origin=fan?w*(.8+Math.sin(time*.13)*.14):ox;
        const end=w*((ray+.5)/fans[fan]+.12*Math.sin(time*.18+ray+fan)),spread=w*(.025+treble*.03);
        const glow=ctx.createLinearGradient(origin,oy,end,h);
        glow.addColorStop(0,white((fan?.07:.12)+treble*.17+pulse*.05));glow.addColorStop(.45,white((fan?.012:.025)+energy*.055));glow.addColorStop(1,white(0));
        ctx.fillStyle=glow;ctx.beginPath();ctx.moveTo(origin,oy);ctx.lineTo(end-spread,h);ctx.lineTo(end+spread,h);ctx.closePath();ctx.fill();
      }
      canvas.dataset.rayFans='2';
      const detail=Math.max(.65,quality),layers=Math.floor((mobile?5:7)*detail),strands=Math.floor((mobile?9:12)*detail),steps=Math.floor((mobile?56:76)*detail);
      // Layer depth controls apparent scale, opacity and parallax; clouds cross
      // the camera gently rather than merely oscillating on a flat baseline.
      for(let layer=layers-1;layer>=0;layer--){
        const depth=(layer/layers+time*.027)%1,scale=.65+depth*.7,fade=Math.sin(depth*Math.PI),alpha=(.12+depth*.16)*fade;
        const cx=w*(.5+Math.sin(time*.18+layer*1.4)*.18*depth),cy=h*(.22+depth*.6)+Math.sin(time*.27+layer)*h*.06;
        const mist=ctx.createRadialGradient(cx,cy,0,cx,cy,unit*(.18+depth*.14));
        mist.addColorStop(0,white((.08+energy*.16)*fade));mist.addColorStop(1,white(0));ctx.fillStyle=mist;ctx.fillRect(cx-unit*.45,cy-unit*.45,unit*.9,unit*.9);
        for(let strand=0;strand<strands;strand++){
          const points=[];
          for(let i=0;i<=steps;i++){
            const t=i/steps,envelope=Math.sin(t*Math.PI),around=strand/strands*TAU;
            const perspective=1/(1-Math.cos(around)*envelope*.22*depth);
            const x=cx+(t-.5)*w*1.35*scale*perspective;
            const y=cy+(Math.sin(t*8+time*.48+layer)*h*.07*scale+Math.sin(t*17-time*(.32+mids*.9)+strand*.13)*envelope*h*(.025+mids*.075)+Math.sin(t*TAU*3-time*1.1-layer)*envelope*h*(bass*.025+pulse*.018)+Math.sin(around)*h*.075*envelope*scale)*perspective;
            points.push([x,y]);
          }
          stroke(points,strand%6===0?`hsla(${strand%12===0?218:273},85%,78%,${(.035+energy*.055+pulse*.035)*fade})`:white(alpha+energy*.16*fade),Math.max(.65,unit/1400*(1+depth)));
        }
      }
      for(let mote=0;mote<(mobile?24:45);mote++){
        const a=mote*2.399963+time*.1,depth=((mote*17%47)/47+time*.014)%1;
        const x=w*.5+Math.cos(a)*w*.45*(.3+depth),y=h*.5+Math.sin(a*.71+time*.1)*h*.36;
        ctx.fillStyle=white(depth*(.18+treble*.32));ctx.beginPath();ctx.arc(x,y,Math.max(.6,unit/600*depth),0,TAU);ctx.fill();
      }
    }
    function spaceLayer(foreground=false) {
      const {w,h,unit,time,bass,mids,treble,energy,color,mobile}=view;
      ctx.globalCompositeOperation='source-over';
      const count=Math.floor((mobile?36:72)*Math.max(.65,quality));
      for(let i=0;i<count;i++){
        const rock=rocks[i];if((rock.z>.7)!==foreground)continue;
        const a=rock.a+time*(.025+rock.z*.022),x=w*.5+Math.cos(a)*w*rock.r*.72,y=h*.51+Math.sin(a)*h*rock.r*.42;
        const size=unit*.0025*rock.size*(.5+rock.z)*(1+bass*.08);
        ctx.save();ctx.translate(x,y);ctx.rotate(rock.spin+time*.12);ctx.fillStyle=foreground?'#9ca4b5':'#555f79';ctx.strokeStyle=color(1,.17+treble*.18);ctx.lineWidth=.7;ctx.beginPath();
        for(let v=0;v<7;v++){const r=size*(.75+.2*Math.sin(v*13+i));const a=v*TAU/7;v?ctx.lineTo(Math.cos(a)*r,Math.sin(a)*r):ctx.moveTo(Math.cos(a)*r,Math.sin(a)*r);}ctx.closePath();ctx.fill();ctx.stroke();ctx.restore();
      }
      if(!foreground){
        const clock=(time+3)%15,comet=clock<9;
        canvas.dataset.comet=comet?'visible':'waiting';
        if(comet){
          const t=clock/9,x=w*(-.2+t*1.5),y=h*(.08+t*.45+.05*Math.sin(time*.35)),length=unit*(.16+energy*.12);
          const tail=ctx.createLinearGradient(x-length,y-length*.36,x,y);tail.addColorStop(0,white(0));tail.addColorStop(.7,color(1,.24+treble*.3));tail.addColorStop(1,white(.9));
          stroke([[x-length,y-length*.36],[x,y]],tail,Math.max(2,unit*.008));stroke([[x-length*.7,y-length*.22],[x,y]],white(.65),Math.max(1,unit*.002));ctx.fillStyle=white(.95);ctx.beginPath();ctx.arc(x,y,Math.max(2,unit*.004),0,TAU);ctx.fill();
        }
        return;
      }
      const clock=(time+4)%24,visible=clock<14;canvas.dataset.ufo=visible?'visible':'waiting';canvas.dataset.asteroidCount=String(count);
      if(!visible)return;
      const t=clock/14,x=w*(-.16+t*1.32),y=h*(.23+.08*Math.sin(t*TAU+time*.09)),r=unit*.035;
      ctx.save();ctx.translate(x,y);ctx.rotate(Math.sin(time*.8)*.12);
      if(clock>4 && clock<10){const beam=ctx.createLinearGradient(0,r*.15,0,r*5);beam.addColorStop(0,white(.18+treble*.18));beam.addColorStop(1,color(0,0));ctx.fillStyle=beam;ctx.beginPath();ctx.moveTo(-r*.3,r*.1);ctx.lineTo(-r*2,r*5);ctx.lineTo(r*2,r*5);ctx.lineTo(r*.3,r*.1);ctx.closePath();ctx.fill();}
      const shell=ctx.createLinearGradient(0,-r,0,r);shell.addColorStop(0,'#f5fbff');shell.addColorStop(.45,'#9fb4cf');shell.addColorStop(1,'#2a3550');ctx.fillStyle=shell;ctx.beginPath();ctx.ellipse(0,0,r*1.5,r*.32,0,0,TAU);ctx.fill();
      ctx.fillStyle='rgba(170,240,255,.65)';ctx.beginPath();ctx.ellipse(0,-r*.18,r*.62,r*.47,0,Math.PI,TAU);ctx.fill();
      for(let light=0;light<7;light++){const lx=(light-3)*r*.35;ctx.fillStyle=color(light,.55+Math.sin(time*2+light)*.18+energy*.2);ctx.beginPath();ctx.arc(lx,r*.08,r*.07*(1+pulse*.4),0,TAU);ctx.fill();}ctx.restore();
    }
    const api={
      render(mode,params) {
        if(disposed)return false;
        view=params;
        const dt=Math.max(0,params.elapsed || 0);
        if(params.measured && dt>0){
          audioTime+=dt;const previous=bassFloor;bassFloor+=(params.bass-bassFloor)*(1-Math.exp(-dt*2));
          if(params.energy>.02 && params.bass>previous+.055 && audioTime-onsetAt>.28){pulse=Math.min(1,(params.bass-previous)*3);onsetAt=audioTime;}
          else pulse*=Math.exp(-dt*4);
          pulse=Math.max(pulse,params.beatPulse || 0);
        } else if(!params.measured)pulse=0;
        if(lastMode!==mode){qualities[lastMode]=quality;quality=qualities[mode]??1;lastMode=mode;particleReady=false;cost=0;frames=0;}
        const started=performance.now();ctx.save();
        try {
          if(mode==='fractal'){view={...params,time:params.fractalTime??params.time};fractal();}else if(mode==='particles')particles();else if(mode==='ambient')ambient();else if(mode==='ethereal')ethereal();else if(mode==='space'){spaceLayer(false);params.earth();spaceLayer(true);}else return false;
        }finally{ctx.restore();}
        // Downgrade detail after sustained expensive frames, never increase it
        // on a brief quiet passage. Each mode retains its own quality across switches.
        cost+=performance.now()-started;frames++;
        if(frames===6){if(cost/frames>16)quality=Math.max(.5,quality*.75);cost=0;frames=0;}
        canvas.dataset.sceneQuality=quality.toFixed(2);
        return true;
      },
      dispose(){disposed=true;discardGPU();if(raster)raster.width=raster.height=1;raster=rasterContext=rasterData=null;}
    };
    scope.cleanup(api.dispose);
    return api;
  }};
})();
