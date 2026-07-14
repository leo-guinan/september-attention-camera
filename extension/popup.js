async function send(message){ return chrome.runtime.sendMessage(message); }
function jsonl(receipts){ return receipts.map(r => JSON.stringify(r)).join('\n') + (receipts.length ? '\n' : ''); }
async function refresh(){
  const s = await send({type:'get-status'});
  document.getElementById('status').textContent = `${s.count} receipts · ${s.config.enabled ? 'enabled' : 'disabled'} · ${s.config.reportUrl || 'local only'}`;
  document.getElementById('latest').textContent = s.receipts?.length ? JSON.stringify(s.receipts[s.receipts.length-1], null, 2) : 'No captures yet.';
  return s;
}
document.getElementById('scan').onclick = async () => { const [tab] = await chrome.tabs.query({active:true,currentWindow:true}); if(tab?.id) chrome.tabs.sendMessage(tab.id,{type:'manual-scan'}); setTimeout(refresh, 800); };
document.getElementById('export').onclick = async () => { const s = await refresh(); const url = 'data:application/x-ndjson;charset=utf-8,' + encodeURIComponent(jsonl(s.receipts || [])); await chrome.downloads?.download?.({url, filename:'metaspn-attention-receipts.jsonl', saveAs:true}); if(!chrome.downloads) navigator.clipboard.writeText(jsonl(s.receipts || [])); };
document.getElementById('clear').onclick = async () => { await send({type:'clear-receipts'}); refresh(); };
document.getElementById('options').onclick = () => chrome.runtime.openOptionsPage();
refresh();
