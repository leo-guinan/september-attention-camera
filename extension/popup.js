async function send(message){ return chrome.runtime.sendMessage(message); }
function jsonl(receipts){ return receipts.map(r => JSON.stringify(r)).join('\n') + (receipts.length ? '\n' : ''); }
function endpointLabel(config){
  const endpoints = config.endpoints || [];
  const enabled = endpoints.filter(e => e.enabled !== false);
  if(enabled.length) return `${enabled.length} endpoint${enabled.length===1?'':'s'}`;
  return config.reportUrl || 'local only';
}
async function refresh(){
  const s = await send({type:'get-status'});
  document.getElementById('status').textContent = `${s.count} receipts · ${s.config.enabled ? 'enabled' : 'disabled'} · ${endpointLabel(s.config)}`;
  document.getElementById('latest').textContent = s.receipts?.length ? JSON.stringify(s.receipts[s.receipts.length-1], null, 2) : 'No captures yet.';
  return s;
}
document.getElementById('scan').onclick = async () => { const [tab] = await chrome.tabs.query({active:true,currentWindow:true}); if(tab?.id) chrome.tabs.sendMessage(tab.id,{type:'manual-scan'}); setTimeout(refresh, 800); };
document.getElementById('ping').onclick = async () => { const res = await send({type:'ping-endpoints'}); document.getElementById('latest').textContent = JSON.stringify(res.results || res, null, 2); await refresh(); };
document.getElementById('export').onclick = async () => { const s = await refresh(); const url = 'data:application/x-ndjson;charset=utf-8,' + encodeURIComponent(jsonl(s.receipts || [])); await chrome.downloads?.download?.({url, filename:'metaspn-attention-receipts.jsonl', saveAs:true}); if(!chrome.downloads) navigator.clipboard.writeText(jsonl(s.receipts || [])); };
document.getElementById('clear').onclick = async () => { await send({type:'clear-receipts'}); refresh(); };
document.getElementById('options').onclick = () => chrome.runtime.openOptionsPage();
refresh();
