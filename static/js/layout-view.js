const layout = (() => {
  "use strict";
  const host = document.getElementById("app");
  if (!host) return null;

  const style = document.createElement("style");
  style.textContent = `
    .layout-text-view{padding:0}.layout-page-stack{display:flex;flex-direction:column;gap:18px}
    .layout-page{position:relative;width:100%;background:#fff;border:1px solid #e4e8ef;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(25,45,75,.04)}
    .layout-page-frame{position:relative;width:100%;overflow:hidden}
    .layout-page-canvas{position:relative;transform-origin:top left;background:#fff;overflow:hidden}
    .layout-span{position:absolute;display:block;white-space:pre;line-height:1.08;user-select:text;color:#17243a}
    .layout-line{position:absolute;pointer-events:none;background:#b9c4d4}
    .layout-rect{position:absolute;pointer-events:none;box-sizing:border-box;border:1px solid #cfd6e2}
    .layout-answer{position:absolute;z-index:20;box-sizing:border-box;min-width:72px;height:26px;padding:2px 7px;border:1px solid #b7c1d0;border-radius:4px;background:rgba(255,255,255,.97);color:#15233b;font:600 13px/20px Inter,system-ui,sans-serif;outline:none}
    .layout-answer:focus{border-color:#213a61;box-shadow:0 0 0 2px rgba(33,58,97,.12)}
  `;
  document.head.appendChild(style);

  function esc(s){return String(s).replace(/[&<>\"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
  function rgb(c){c=Number(c||0);return `rgb(${(c>>16)&255},${(c>>8)&255},${c&255})`}
  function font(f){f=String(f||"").toLowerCase();if(f.includes("mono"))return "'IBM Plex Mono',monospace";if(f.includes("times")||f.includes("serif"))return "Georgia,serif";return "Inter,Arial,Helvetica,sans-serif"}
  async function api(path,opts){const r=await fetch(path,opts);if(!r.ok)throw new Error(`${r.status}: ${await r.text()}`);return (r.headers.get("content-type")||"").includes("json")?r.json():r}

  function pageHtml(page,prefix,from,to){
    const spans=(page.spans||[]).map((s,i)=>{const b=s.bbox;const st=`left:${b[0]}px;top:${b[1]}px;font-size:${s.size}px;color:${rgb(s.color)};font-family:${font(s.font)};font-weight:${s.bold?700:400};font-style:${s.italic?"italic":"normal"}`;return `<span class="layout-span" data-i="${i}" style="${st}">${esc(s.text)}</span>`}).join("");
    const shapes=(page.shapes||[]).map(s=>{const b=s.bbox;if(s.type==="rect")return `<div class="layout-rect" style="left:${b[0]}px;top:${b[1]}px;width:${b[2]-b[0]}px;height:${b[3]-b[1]}px"></div>`;if(s.type==="hline")return `<div class="layout-line" style="left:${b[0]}px;top:${b[1]}px;width:${Math.max(1,b[2]-b[0])}px;height:1px"></div>`;if(s.type==="vline")return `<div class="layout-line" style="left:${b[0]}px;top:${b[1]}px;width:1px;height:${Math.max(1,b[3]-b[1])}px"></div>`;return ""}).join("");
    const answers=(page.answer_boxes||[]).filter(a=>a.question>=from&&a.question<=to).map(a=>{const b=a.bbox;return `<input class="layout-answer" data-q="${a.question}" data-prefix="${prefix}" aria-label="Answer for question ${a.question}" autocomplete="off" spellcheck="false" style="left:${b[0]}px;top:${b[1]}px;width:${Math.max(72,b[2]-b[0])}px">`}).join("");
    return `<div class="layout-page"><div class="layout-page-frame"><div class="layout-page-canvas" style="width:${page.width}px;height:${page.height}px">${shapes}${spans}${answers}</div></div></div>`;
  }

  function buildMaterial(content,kind,cfg,prefix){const pages=content?.[kind]?.pages||[];const groups=kind==="reading"?(cfg.reading.passages||[]):(cfg.listening.parts||[]);if(!pages.length)return "";let html='<div class="layout-text-view"><div class="layout-page-stack">';pages.forEach(p=>{let from=0,to=999;groups.forEach(g=>{if((g.pages||[]).includes(p.page)){from=g.questions[0];to=g.questions[1]}});html+=pageHtml(p,prefix,from,to)});return html+'</div></div>'}
  function wireAnswers(root){root.querySelectorAll('.layout-answer').forEach(input=>{const q=input.dataset.q,prefix=input.dataset.prefix,sheet=document.getElementById(`${prefix}-${q}`);if(!sheet)return;input.value=sheet.value||"";input.addEventListener('input',()=>{sheet.value=input.value;sheet.dispatchEvent(new Event('input'))});sheet.addEventListener('input',()=>{if(document.activeElement!==input)input.value=sheet.value});input.addEventListener('focus',()=>{if(typeof syncNavCurrent==='function')syncNavCurrent(prefix,q)})})}

  function replaceStart(kind){
    const fn=async(d)=>{
      const mockId=d?.mock; const testName=d?.test;
      if(!mockId||!testName)throw new Error("Missing mock/test selection");
      const cfg=await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}`);const section=cfg[kind];if(!section)throw new Error(`No ${kind} configuration`);
      const seconds=(section.duration_minutes||(kind==="listening"?40:60))*60;
      const attempt=await api('/api/attempts/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mock_id:mockId,test_name:testName,section:kind,time_allowed_seconds:seconds})});
      const content=await api(`/api/mocks/${encodeURIComponent(mockId)}/tests/${encodeURIComponent(testName)}/content`);
      const groups=(kind==='reading'?section.passages:section.parts).map((g,i)=>({label:kind==='reading'?`Passage ${i+1}`:`Part ${g.part_number||i+1}`,from:g.questions[0],to:g.questions[1]}));
      const prefix=kind==='reading'?'ans':'lans';const totalQ=groups.reduce((n,g)=>n+g.to-g.from+1,0);const material=buildMaterial(content,kind,cfg,prefix);if(!material)throw new Error('Layout content is not available. Run the mock scaffold again.');
      const shell=document.getElementById('app');
      shell.innerHTML=`<div class="exam-bar"><div class="exam-bar-left"><button class="exam-exit" id="layoutExit">← Exit</button><span class="exam-divider"></span><span class="exam-type">IELTS</span><strong>${kind==='reading'?'Reading':'Listening'}</strong></div><div class="exam-bar-right"><span id="answeredCount">0 / ${totalQ} answered</span><button class="btn btn-ghost" id="layoutSettings">⚙ Settings</button><button class="btn btn-ghost" id="layoutHide">Hide</button><span class="timer-box">TIME REMAINING <strong id="timer">${kind==='reading'?'60:00':'40:00'}</strong></span></div></div><div class="exam-shell"><div class="exam-material">${material}</div><div class="exam-answers"><h3>Answer sheet</h3>${typeof answerSheetHtml==='function'?answerSheetHtml(groups,prefix):''}<div class="submit-area"><button class="btn btn-primary" id="submitBtn">Submit ${kind}</button></div></div></div>${typeof navBarHtml==='function'?navBarHtml(groups,prefix):''}`;
      window._navPrefix=prefix;document.body.classList.add('has-exam-navbar');if(typeof wireAnswerSheet==='function')wireAnswerSheet(shell);wireAnswers(shell);if(typeof syncNavAnswered==='function')syncNavAnswered(prefix);
      shell.querySelectorAll('.layout-page').forEach(pageEl=>{const canvas=pageEl.querySelector('.layout-page-canvas'),frame=pageEl.querySelector('.layout-page-frame'),w=parseFloat(canvas.style.width),h=parseFloat(canvas.style.height);const size=()=>{const scale=Math.min(1,Math.max(280,frame.clientWidth)/w);canvas.style.transform=`scale(${scale})`;frame.style.height=`${h*scale}px`};size();window.addEventListener('resize',size)});
      shell.querySelector('#layoutHide').addEventListener('click',()=>shell.classList.toggle('layout-hidden-material'));shell.querySelector('#layoutSettings').addEventListener('click',()=>typeof toast==='function'&&toast('Settings are unchanged from the standard exam view.'));shell.querySelector('#layoutExit').addEventListener('click',()=>typeof navigateTo==='function'?navigateTo('home'):location.reload());
      shell.querySelector('#submitBtn').addEventListener('click',()=>{const left=typeof unansweredCount==='function'?unansweredCount(prefix):0;const submit=()=>typeof submitSection==='function'&&submitSection({attemptId:attempt.attempt_id,mockId:mockId,testName:testName,section:kind,prefix:prefix,label:kind==='reading'?'Reading':'Listening',auto:false,groups:groups});if(left>0&&typeof confirmModal==='function')confirmModal({title:'Submit with blanks?',body:`${left} question${left===1?' is':'s are'} still unanswered. Blank answers are marked wrong.`,confirmLabel:'Submit anyway',onConfirm:submit});else submit()});
      if(typeof startTimer==='function')startTimer(seconds,r=>typeof tickTimer==='function'&&tickTimer(r,300),()=>typeof submitSection==='function'&&submitSection({attemptId:attempt.attempt_id,mockId:mockId,testName:testName,section:kind,prefix:prefix,label:kind==='reading'?'Reading':'Listening',auto:true,groups:groups}));
    };
    if(kind==='reading')routes.startReading=fn;else routes.startListening=fn;
  }
  replaceStart('reading');replaceStart('listening');window.__layoutTextReady=true;
})();
