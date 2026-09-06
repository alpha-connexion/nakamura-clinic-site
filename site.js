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

// 2. STICKY BAR — one implementation, one behaviour. On pages with a #heroCall anchor
//    (index.html) the bar appears once the hero CTA scrolls away. On every other page
//    (no #heroCall) it shows immediately.
(function(){
  var hero = document.getElementById('heroCall'), bar = document.getElementById('mbar');
  if(!bar) return;
  if(!hero || !('IntersectionObserver' in window)){ bar.classList.add('show'); return; }
  new IntersectionObserver(function(es){
    es.forEach(function(e){ bar.classList.toggle('show', !e.isIntersecting); });
  }).observe(hero);
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
