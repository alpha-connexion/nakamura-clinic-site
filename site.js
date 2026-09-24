// なかむらクリニック — shared site behaviour. Loaded with defer from every page.
// 表・モバイル一覧・フッター要約・JSON-LD は同じコミットで直す。

// 1. TODAY HIGHLIGHT — desktop column tint + mobile row pin. Guarded: only runs on pages
//    that actually carry the 診療時間表 (index.html only, per SINGLE HOME rule).
(function(){
  if(!(document.querySelector('.hours-table') || document.getElementById('hoursList'))) return;
  var d = String(new Date().getDay());
  document.querySelectorAll('.hours-table [data-day="'+d+'"]').forEach(function(el){
    if(!el.classList.contains('col-closed')) el.classList.add('col-today');
  });
  var th = document.querySelector('.hours-table th[data-day="'+d+'"]');
  if(th && d !== '0' && d !== '4'){
    var t = document.createElement('span');
    t.className = 'th-tag'; t.textContent = '本日';
    th.appendChild(t);
  }
  var list = document.getElementById('hoursList');
  var row = list && list.querySelector('.day-row[data-day="'+d+'"]');
  if(row){
    row.classList.add('is-today');
    var tag = document.createElement('span');
    tag.className = 'today-tag'; tag.textContent = '本日';
    row.insertBefore(tag, row.querySelector('.states'));
  }
})();

// 2. STICKY BAR — one filled phone button on screen, never two. Below 768px the bar is the
//    only chrome phone. It shows whenever no .btn-call inside <main> (hero, .call-card,
//    closing band) is in the clear band between the sticky header and the bar itself, and
//    hides while one is. Pages without a .btn-call (the two document pages) show it at once.
//    JS off: styles.css scopes the hidden state to html.js, so the bar simply stays up.
(function(){
  var bar = document.getElementById('mbar');
  if(!bar) return;
  var calls = [].slice.call(document.querySelectorAll('main .btn-call'));
  if(!calls.length || !('IntersectionObserver' in window)){ bar.classList.add('show'); return; }
  var hdr = document.querySelector('header'),
      top = hdr ? Math.round(hdr.getBoundingClientRect().height) : 0,
      low = Math.round(bar.getBoundingClientRect().height),
      inBand = [], io, r, i;
  function sync(){
    for(var k = 0; k < inBand.length; k++){ if(inBand[k]){ bar.classList.remove('show'); return; } }
    bar.classList.add('show');
  }
  // First frame decided synchronously, so the bar does not slide in on load where it belongs.
  for(i = 0; i < calls.length; i++){
    r = calls[i].getBoundingClientRect();
    inBand[i] = r.bottom > top && r.top < innerHeight - low;
  }
  sync();
  io = new IntersectionObserver(function(es){
    for(var k = 0; k < es.length; k++) inBand[calls.indexOf(es[k].target)] = es[k].isIntersecting;
    sync();
  }, { rootMargin: (-top) + 'px 0px ' + (-low) + 'px 0px', threshold: 0 });
  for(i = 0; i < calls.length; i++) io.observe(calls[i]);
})();

// 3. LANE SWITCH — 体×心 lane switch. APG tablist, hash deep links (#naika / #seishinka),
//    View Transitions, reduced-motion aware. Guarded: only runs where #care exists.
(function(){
  var sec=document.getElementById('care');if(!sec)return;
  var tabs=[].slice.call(sec.querySelectorAll('[role="tab"]'));
  var still=matchMedia('(prefers-reduced-motion: reduce)');
  function panelOf(t){return document.getElementById(t.getAttribute('aria-controls'));}
  function apply(tab){
    tabs.forEach(function(t){
      var on=t===tab;
      t.setAttribute('aria-selected',on?'true':'false');t.tabIndex=on?0:-1;
      panelOf(t).classList.toggle('is-on',on);
    });
    sec.dataset.lane=tab.dataset.lane;
  }
  function go(tab,focus){
    var href=tab.getAttribute('href');
    if(location.hash!==href)history.replaceState(null,'',href);
    if(tab.getAttribute('aria-selected')!=='true'){
      (document.startViewTransition&&!still.matches)?document.startViewTransition(function(){apply(tab);}):apply(tab);
    }
    if(focus)tab.focus();
  }
  function tabFor(hash){for(var i=0;i<tabs.length;i++){if(tabs[i].getAttribute('href')===hash)return tabs[i];}return null;}
  sec.addEventListener('click',function(e){
    var t=e.target.closest('[role="tab"]');if(!t)return;
    e.preventDefault();go(t);
  });
  sec.addEventListener('keydown',function(e){
    var i=tabs.indexOf(e.target);if(i<0)return;
    var n={ArrowRight:i+1,ArrowLeft:i-1,Home:0,End:tabs.length-1}[e.key];if(n===undefined)return;
    e.preventDefault();go(tabs[(n+tabs.length)%tabs.length],true);
  });
  addEventListener('hashchange',function(){var t=tabFor(location.hash);if(t)go(t);});
  var t0=tabFor(location.hash);
  if(t0){apply(t0);sec.scrollIntoView({behavior:'instant',block:'start'});}
})();

// 4. SETTLE REVEALS — a block comes to rest, once, then the node is forgotten.
//    APPEND to site.js after IIFE 3 (LANE SWITCH). Self-guarded, no globals.
//    The hidden start state lives in styles.css under html.js (set inline in
//    <head>), and applies only to [data-reveal] / [data-reveal-mark] authored in
//    the HTML — so with JS off nothing is ever hidden, and no element is ever
//    visible-then-hidden. If this file never arrives, the --rv-fail keyframes
//    reveal everything at 2.4s; html.rv-go below is what disarms them, and it is
//    set LAST, only once the observer is wired.
(function(){
  var root = document.documentElement,
      nodes = [].slice.call(document.querySelectorAll('[data-reveal],[data-reveal-mark]')),
      still = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)'),
      tops = [], fold, io, i;
  function showAll(){ for(var j=0;j<nodes.length;j++) nodes[j].classList.add('rv-in'); }
  function done(){ root.classList.add('rv-go'); }          // cancel the 2.4s CSS failsafe
  if(!nodes.length){ done(); return; }
  // Reduced motion, or a browser without IntersectionObserver: everything visible,
  // nothing observed. Same shape as the sticky-bar guard in IIFE 2.
  if(!('IntersectionObserver' in window) || (still && still.matches)){ showAll(); done(); return; }
  try{
    io = new IntersectionObserver(function(es){
      for(var k=0;k<es.length;k++){
        // Reveal on enter, and ALSO reveal anything already above the viewport:
        // browser scroll restoration and #deep links can land past a block, and
        // such a block would otherwise never intersect and stay at opacity:0.
        if(!es[k].isIntersecting && es[k].boundingClientRect.top > 0) continue;
        es[k].target.classList.add('rv-in');
        io.unobserve(es[k].target);                        // one arrival per element, ever
      }
    }, { rootMargin: (innerWidth < 768 ? '0px 0px 12% 0px' : '0px 0px -8% 0px'), threshold: 0 });
    // A POSITIVE bottom margin fires EARLIER (it grows the root); a negative one
    // fires later. Phones get +12% so a block is at rest before it is read;
    // desktop gets -8% so a block settles just as it composes into view.
  }catch(e){ showAll(); done(); return; }
  fold = innerHeight * (innerWidth < 768 ? 1.12 : 0.92);   // same line the observer uses
  for(i=0;i<nodes.length;i++) tops[i] = nodes[i].getBoundingClientRect().top;   // read…
  for(i=0;i<nodes.length;i++){                                                  // …then write
    if(tops[i] < fold) nodes[i].classList.add('rv-now');   // on screen at load → no fade
    io.observe(nodes[i]);
  }
  done();
})();

// 5. MENU — the phone header menu (<768px). JS off: .hdr-menu is a plain link to the
//    footer's site index (#site-index) and nothing here runs. JS on: it becomes a
//    disclosure button for nav.main (#gnav), which styles.css shows as a full-width sheet
//    under the sticky header while html.menu-open is set. No motion: the sheet is there or
//    not (MOTION — only [data-reveal] moves). While it is open the page behind does not
//    scroll and the .mbar stays up, so the call is still one thumb away.
(function(){
  var btn = document.querySelector('.hdr-menu'),
      nav = document.getElementById('gnav'),
      hdr = document.querySelector('header');
  if(!btn || !nav || !hdr || !window.matchMedia) return;
  var root = document.documentElement, mq = matchMedia('(max-width: 767px)');
  btn.setAttribute('role', 'button');
  btn.setAttribute('aria-controls', 'gnav');
  btn.setAttribute('aria-expanded', 'false');
  function isOpen(){ return root.classList.contains('menu-open'); }
  function set(open){
    root.classList.toggle('menu-open', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  function reset(){ if(isOpen()) set(false); }
  btn.addEventListener('click', function(e){
    if(!mq.matches) return;                            // >=768px the control is display:none anyway
    e.preventDefault();
    set(!isOpen());
  });
  btn.addEventListener('keydown', function(e){         // an <a role="button"> must answer Space as well as Enter
    if(e.key === ' ' || e.key === 'Spacebar'){ e.preventDefault(); btn.click(); }
  });
  hdr.addEventListener('click', function(e){           // any other header link (a sheet row, the brand): close
    var a = e.target.closest('a');                     // first, then the browser follows it — same-page
    if(a && a !== btn) reset();                        // #care / #hours / #docs / #access scroll as usual
  });
  document.addEventListener('keydown', function(e){
    if((e.key === 'Escape' || e.key === 'Esc') && isOpen()){ set(false); btn.focus(); }
  });
  document.addEventListener('focusin', function(e){    // Tab past the last row closes the sheet instead of
    if(isOpen() && !hdr.contains(e.target)) set(false); // focusing content hidden behind it
  });
  if(mq.addEventListener) mq.addEventListener('change', reset); else if(mq.addListener) mq.addListener(reset);
  addEventListener('pageshow', reset);                 // bfcache: Back never returns to an open sheet
})();
