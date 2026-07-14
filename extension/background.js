const DEFAULTS = {
  enabled: true,
  reportUrl: '',
  operatorLabel: 'anonymous-sensor',
  quaiPayoutAddress: '',
  rawIdentityExport: false
};

async function getConfig(){
  const got = await chrome.storage.local.get(['config']);
  return {...DEFAULTS, ...(got.config || {})};
}

async function getReceipts(){
  const got = await chrome.storage.local.get(['receipts']);
  return Array.isArray(got.receipts) ? got.receipts : [];
}

async function saveReceipt(receipt){
  const config = await getConfig();
  if(!config.enabled) return {stored:false, reported:false, reason:'disabled'};
  const enriched = {...receipt, operator_label: config.operatorLabel, quai_payout_address: config.quaiPayoutAddress || null, local_received_at: new Date().toISOString()};
  const receipts = await getReceipts();
  receipts.push(enriched);
  while(receipts.length > 1000) receipts.shift();
  await chrome.storage.local.set({receipts});
  let reported = false;
  let reportError = '';
  if(config.reportUrl){
    try{
      const res = await fetch(config.reportUrl, {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify(enriched)});
      reported = res.ok;
      if(!res.ok) reportError = String(res.status);
    }catch(err){ reportError = String(err && err.message || err); }
  }
  await chrome.action.setBadgeText({text:String(receipts.length).slice(-4)});
  await chrome.action.setBadgeBackgroundColor({color: reported ? '#2f7d32' : '#9a6b00'});
  return {stored:true, reported, reportError};
}

chrome.runtime.onInstalled.addListener(async () => {
  const got = await chrome.storage.local.get(['config']);
  if(!got.config) await chrome.storage.local.set({config: DEFAULTS, receipts: []});
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if(message?.type === 'attention-capture') sendResponse(await saveReceipt(message.receipt));
    else if(message?.type === 'get-status') sendResponse({config: await getConfig(), count: (await getReceipts()).length, receipts: await getReceipts()});
    else if(message?.type === 'clear-receipts'){ await chrome.storage.local.set({receipts: []}); await chrome.action.setBadgeText({text:''}); sendResponse({ok:true}); }
    else sendResponse({ok:false, error:'unknown message'});
  })();
  return true;
});
