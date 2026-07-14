(() => {
  const api = globalThis.MetaSPNSensorTargets;
  if(!api) return;

  let lastCaptureKey = '';
  function pageText(){ return document.body ? document.body.innerText || '' : ''; }
  function capture(mode='passive'){
    const target = api.detectTarget(location.href);
    if(!target) return;
    const text = pageText();
    const links = Array.from(document.querySelectorAll('a[href]')).map(a => a.href).slice(0, 500);
    const tweetIds = Array.from(new Set(api.extractTweetIdsFromText([location.href, ...links].join('\n'))));
    const stats = api.extractVisibleStats(text, location.href);
    const derived = api.deriveAttention(stats);
    const key = [location.href, stats.followers, stats.subscribers, stats.likes, stats.reposts, stats.replies, stats.views, text.length].join('|');
    if(mode === 'passive' && key === lastCaptureKey) return;
    lastCaptureKey = key;
    const receipt = {
      schema_version: 'attention-sensor-v1',
      captured_at: new Date().toISOString(),
      page_url: location.href,
      page_title: document.title || '',
      capture_mode: mode,
      tweet_ids: tweetIds,
      target: {id: target.id, name: target.name, surface: target.surface, handle: target.matchedHandle || target.twitter},
      visible_stats: stats,
      derived,
      coverage: {
        visible_dom_only: true,
        hidden_replies_missing: true,
        private_analytics_missing: true,
        authenticated_platform_api_not_used: true
      }
    };
    chrome.runtime.sendMessage({type:'attention-capture', receipt});
  }

  const schedule = (() => {
    let timer = null;
    return (mode='passive') => {
      clearTimeout(timer);
      timer = setTimeout(() => capture(mode), 900);
    };
  })();

  schedule('page_load');
  const observer = new MutationObserver(() => schedule('mutation'));
  if(document.body) observer.observe(document.body, {childList:true, subtree:true, characterData:true});
  let lastUrl = location.href;
  setInterval(() => {
    if(location.href !== lastUrl){
      lastUrl = location.href;
      schedule('spa_navigation');
    }
  }, 1200);
  chrome.runtime.onMessage.addListener((message) => {
    if(message && message.type === 'manual-scan') capture('manual');
  });
})();
