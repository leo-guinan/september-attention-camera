(function(global){
  const TARGETS = [
    {
      id: 'hitchhikers',
      name: "Hitchhiker's Guide to the Future",
      twitter: 'hitchhikerglitch',
      hosts: ['hitchhikersguidetothefuture.com'],
      xHandles: ['hitchhikerglitch'],
      kind: 'guide'
    },
    {
      id: 'psyop',
      name: 'Psyop Report',
      twitter: 'DefenderOfBasic',
      hosts: ['www.psyop.report','psyop.report'],
      xHandles: ['DefenderOfBasic'],
      kind: 'defender'
    },
    {
      id: 'rivalvoices',
      name: 'Rival Voices',
      twitter: 'nosilverv',
      hosts: ['rivalvoices.substack.com'],
      xHandles: ['nosilverv'],
      kind: 'rival'
    },
    {
      id: 'vatstack',
      name: 'The Vat Stack',
      twitter: 'TheVatStack',
      hosts: ['thevatstack.substack.com'],
      xHandles: ['TheVatStack'],
      kind: 'vat'
    }
  ];

  function normalizeHandle(value){
    return String(value || '').replace(/^@/, '').toLowerCase();
  }

  function detectTarget(url){
    const u = new URL(url);
    const host = u.hostname.toLowerCase();
    const path = u.pathname;
    if(host === 'x.com' || host === 'twitter.com'){
      const handle = normalizeHandle(path.split('/').filter(Boolean)[0]);
      if(!handle || ['home','search','notifications','messages','i'].includes(handle)) return null;
      const target = TARGETS.find(t => t.xHandles.some(h => normalizeHandle(h) === handle));
      return target ? {...target, surface: 'x_profile', matchedHandle: handle} : null;
    }
    const target = TARGETS.find(t => t.hosts.includes(host));
    if(target){
      return {...target, surface: host.includes('substack') || host.includes('psyop.report') ? 'substack_or_publication' : 'website'};
    }
    return null;
  }

  function parseCompactNumber(text){
    const raw = String(text || '').replace(/,/g,'').trim();
    const match = raw.match(/([0-9]+(?:\.[0-9]+)?)\s*([KMB])?/i);
    if(!match) return null;
    const n = Number(match[1]);
    const unit = (match[2] || '').toUpperCase();
    const mult = unit === 'B' ? 1e9 : unit === 'M' ? 1e6 : unit === 'K' ? 1e3 : 1;
    return Math.round(n * mult);
  }

  function extractVisibleStats(text, url){
    const body = String(text || '').replace(/\s+/g, ' ').trim();
    const stats = {followers:null, following:null, subscribers:null, posts:null, likes:null, reposts:null, replies:null, views:null, publicNumbers:[]};
    const patterns = [
      ['followers', /([0-9][0-9,]*(?:\.[0-9]+)?\s*[KMB]?)\s+Followers/i],
      ['following', /([0-9][0-9,]*(?:\.[0-9]+)?\s*[KMB]?)\s+Following/i],
      ['subscribers', /([0-9][0-9,]*(?:\.[0-9]+)?\s*[KMB]?)\s+(?:subscribers|subscriber)/i],
      ['posts', /([0-9][0-9,]*(?:\.[0-9]+)?\s*[KMB]?)\s+(?:posts|articles)/i],
      ['views', /([0-9][0-9,]*(?:\.[0-9]+)?\s*[KMB]?)\s+(?:views|impressions)/i]
    ];
    for(const [key,re] of patterns){
      const m = body.match(re);
      if(m) stats[key] = parseCompactNumber(m[1]);
    }
    const ariaMetrics = Array.from(body.matchAll(/([0-9][0-9,]*(?:\.[0-9]+)?\s*[KMB]?)\s+(Replies|Reposts|Likes|Views)/gi));
    for(const m of ariaMetrics.slice(0,20)){
      const key = m[2].toLowerCase();
      stats[key === 'reposts' ? 'reposts' : key] = Math.max(stats[key] || 0, parseCompactNumber(m[1]) || 0);
    }
    stats.publicNumbers = Array.from(body.matchAll(/\b([0-9][0-9,]{0,8})(?:\b)/g)).slice(0,40).map(m => Number(m[1].replace(/,/g,''))).filter(n => Number.isFinite(n));
    stats.url = url;
    return stats;
  }


  function extractTweetIdsFromText(text){
    const ids = new Set();
    const source = String(text || '');
    for(const m of source.matchAll(/(?:x\.com|twitter\.com)\/[^\s/?#]+\/status\/(\d{5,25})/gi)) ids.add(m[1]);
    for(const m of source.matchAll(/\/status\/(\d{5,25})/gi)) ids.add(m[1]);
    return Array.from(ids);
  }

  function deriveAttention(stats){
    const interactions = (stats.likes || 0) + (stats.reposts || 0) + (stats.replies || 0);
    const audience = stats.followers ?? stats.subscribers ?? null;
    const exposure = stats.views ?? null;
    const attention = Math.round((interactions * 1.2) + ((audience || 0) * 0.015) + ((exposure || 0) * 0.004));
    return {
      audience,
      interactions,
      exposure,
      attention,
      trustBasis: audience === null ? 'visible_interactions_only' : 'visible_audience_and_interactions'
    };
  }

  global.MetaSPNSensorTargets = {TARGETS, detectTarget, extractVisibleStats, deriveAttention, parseCompactNumber, extractTweetIdsFromText};
  if(typeof module !== 'undefined') module.exports = global.MetaSPNSensorTargets;
})(typeof globalThis !== 'undefined' ? globalThis : this);
