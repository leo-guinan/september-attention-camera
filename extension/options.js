const OFFICIAL_ENDPOINT={name:'MetaSPN inbound',url:'https://inbound.metaspn.network/api/sensor',enabled:true,rewardHint:'MetaSPN data router; downstreams own rewards',filters:{targetIds:[],urlPatterns:[]}};
const DEFAULTS={enabled:true,reportUrl:'',endpoints:[],operatorLabel:'anonymous-sensor',quaiPayoutAddress:''};
function pretty(value){return JSON.stringify(value,null,2)}
async function send(message){return chrome.runtime.sendMessage(message)}
function parseEndpoints(){
  const text=endpointsJson.value.trim();
  if(!text) return [];
  const parsed=JSON.parse(text);
  if(!Array.isArray(parsed)) throw new Error('endpoints JSON must be an array');
  return parsed;
}
async function load(){const got=await chrome.storage.local.get(['config']); const c={...DEFAULTS,...(got.config||{})}; enabled.checked=!!c.enabled; operatorLabel.value=c.operatorLabel; quaiPayoutAddress.value=c.quaiPayoutAddress||''; endpointsJson.value=pretty(c.endpoints||[]);}
async function saveConfig(){
  const endpoints=parseEndpoints();
  const res=await send({type:'set-config',config:{enabled:enabled.checked,operatorLabel:operatorLabel.value.trim()||DEFAULTS.operatorLabel,quaiPayoutAddress:quaiPayoutAddress.value.trim(),endpoints}});
  endpointsJson.value=pretty(res.config.endpoints||[]);
  saved.textContent=' saved'; setTimeout(()=>saved.textContent='',1500)
}
save.onclick=async()=>{try{await saveConfig()}catch(err){pingStatus.textContent='Save failed: '+err.message}};
useOfficial.onclick=async()=>{try{const endpoints=parseEndpoints(); if(!endpoints.some(e=>e.url===OFFICIAL_ENDPOINT.url)) endpoints.push(OFFICIAL_ENDPOINT); endpointsJson.value=pretty(endpoints); await saveConfig();}catch(err){pingStatus.textContent='Add failed: '+err.message}};
clearEndpoints.onclick=async()=>{endpointsJson.value='[]'; await saveConfig();};
ping.onclick=async()=>{try{await saveConfig(); const res=await send({type:'ping-endpoints'}); pingStatus.textContent=pretty(res.results||res);}catch(err){pingStatus.textContent='Ping failed: '+err.message}};
load();
