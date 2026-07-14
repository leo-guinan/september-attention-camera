const OFFICIAL_ENDPOINT = {
  name: 'MetaSPN inbound',
  url: 'https://inbound.metaspn.network/api/sensor',
  enabled: false,
  rewardHint: '1 QUAI first-seen tweet; duplicates validation pending',
  filters: {targetIds: [], urlPatterns: []}
};

const DEFAULTS = {
  enabled: true,
  reportUrl: '',
  endpoints: [],
  operatorLabel: 'anonymous-sensor',
  quaiPayoutAddress: '',
  rawIdentityExport: false
};

function normalizeEndpoint(endpoint){
  if(!endpoint || !endpoint.url) return null;
  return {
    name: String(endpoint.name || endpoint.url).trim(),
    url: String(endpoint.url || '').trim().replace(/\/+$/, ''),
    enabled: endpoint.enabled !== false,
    rewardHint: String(endpoint.rewardHint || '').trim(),
    filters: {
      targetIds: Array.isArray(endpoint.filters?.targetIds) ? endpoint.filters.targetIds.map(String).filter(Boolean) : [],
      urlPatterns: Array.isArray(endpoint.filters?.urlPatterns) ? endpoint.filters.urlPatterns.map(String).filter(Boolean) : []
    }
  };
}

function migrateEndpoints(config){
  const endpoints = Array.isArray(config.endpoints) ? config.endpoints.map(normalizeEndpoint).filter(Boolean) : [];
  if(config.reportUrl && !endpoints.some(e => e.url === config.reportUrl.replace(/\/+$/, ''))){
    endpoints.push(normalizeEndpoint({name:'Legacy endpoint', url:config.reportUrl, enabled:true, rewardHint:'legacy report URL'}));
  }
  return endpoints;
}

async function getConfig(){
  const got = await chrome.storage.local.get(['config']);
  const config = {...DEFAULTS, ...(got.config || {})};
  config.endpoints = migrateEndpoints(config);
  return config;
}

async function setConfig(config){
  const normalized = {...DEFAULTS, ...config};
  normalized.endpoints = migrateEndpoints(normalized);
  normalized.reportUrl = normalized.endpoints.find(e => e.enabled)?.url || '';
  await chrome.storage.local.set({config: normalized});
  return normalized;
}

async function getReceipts(){
  const got = await chrome.storage.local.get(['receipts']);
  return Array.isArray(got.receipts) ? got.receipts : [];
}

function endpointMatches(endpoint, receipt){
  const filters = endpoint.filters || {};
  const targetIds = filters.targetIds || [];
  const urlPatterns = filters.urlPatterns || [];
  if(targetIds.length){
    const targetId = String(receipt?.target?.id || '');
    if(!targetIds.includes(targetId)) return false;
  }
  if(urlPatterns.length){
    const pageUrl = String(receipt?.page_url || '');
    let matched = false;
    for(const pattern of urlPatterns){
      try{ if(new RegExp(pattern).test(pageUrl)){ matched = true; break; } }
      catch(_err){ if(pageUrl.includes(pattern)){ matched = true; break; } }
    }
    if(!matched) return false;
  }
  return true;
}

async function pingEndpoint(endpoint){
  const normalized = normalizeEndpoint(endpoint);
  if(!normalized) return {ok:false, error:'invalid endpoint'};
  const started = Date.now();
  const pingUrl = normalized.url.replace(/\/api\/sensor$/, '/api/sensor/ping');
  const policyUrl = normalized.url.replace(/\/api\/sensor$/, '/api/sensor/policy.json');
  const result = {endpoint: normalized, ok:false, ping_url:pingUrl, policy_url:policyUrl, latency_ms:null, policy:null, error:''};
  try{
    const ping = await fetch(pingUrl, {method:'GET', cache:'no-store'});
    result.latency_ms = Date.now() - started;
    if(!ping.ok) throw new Error('ping '+ping.status);
    const pingBody = await ping.json().catch(() => ({}));
    const policy = await fetch(policyUrl, {method:'GET', cache:'no-store'});
    if(policy.ok) result.policy = await policy.json().catch(() => null);
    result.ok = !!pingBody.ok || ping.ok;
  }catch(err){
    result.error = String(err && err.message || err);
  }
  return result;
}

async function pingEndpoints(){
  const config = await getConfig();
  const endpoints = config.endpoints.length ? config.endpoints : [OFFICIAL_ENDPOINT];
  return Promise.all(endpoints.map(pingEndpoint));
}

async function saveReceipt(receipt){
  const config = await getConfig();
  if(!config.enabled) return {stored:false, reported:false, reason:'disabled'};
  const enriched = {...receipt, operator_label: config.operatorLabel, quai_payout_address: config.quaiPayoutAddress || null, local_received_at: new Date().toISOString()};
  const receipts = await getReceipts();
  receipts.push(enriched);
  while(receipts.length > 1000) receipts.shift();
  await chrome.storage.local.set({receipts});

  const endpointResults = [];
  for(const endpoint of config.endpoints.filter(e => e.enabled)){
    if(!endpointMatches(endpoint, enriched)){
      endpointResults.push({endpoint:endpoint.url, name:endpoint.name, skipped:true, reason:'filter'});
      continue;
    }
    try{
      const res = await fetch(endpoint.url, {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(enriched)});
      endpointResults.push({endpoint:endpoint.url, name:endpoint.name, ok:res.ok, status:res.status, response: await res.json().catch(() => null)});
    }catch(err){ endpointResults.push({endpoint:endpoint.url, name:endpoint.name, ok:false, error:String(err && err.message || err)}); }
  }
  const reported = endpointResults.some(r => r.ok);
  await chrome.action.setBadgeText({text:String(receipts.length).slice(-4)});
  await chrome.action.setBadgeBackgroundColor({color: reported ? '#2f7d32' : '#9a6b00'});
  return {stored:true, reported, endpointResults};
}

chrome.runtime.onInstalled.addListener(async () => {
  const got = await chrome.storage.local.get(['config']);
  if(!got.config) await chrome.storage.local.set({config: DEFAULTS, receipts: []});
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if(message?.type === 'attention-capture') sendResponse(await saveReceipt(message.receipt));
    else if(message?.type === 'get-status') sendResponse({config: await getConfig(), count: (await getReceipts()).length, receipts: await getReceipts()});
    else if(message?.type === 'set-config') sendResponse({ok:true, config: await setConfig(message.config || {})});
    else if(message?.type === 'ping-endpoints') sendResponse({ok:true, results: await pingEndpoints()});
    else if(message?.type === 'clear-receipts'){ await chrome.storage.local.set({receipts: []}); await chrome.action.setBadgeText({text:''}); sendResponse({ok:true}); }
    else sendResponse({ok:false, error:'unknown message'});
  })();
  return true;
});
