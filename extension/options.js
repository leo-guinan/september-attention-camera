const OFFICIAL_REPORT_URL='https://inbound.metaspn.network/api/sensor';
const DEFAULTS={enabled:true,reportUrl:'',operatorLabel:'anonymous-sensor',quaiPayoutAddress:''};
async function load(){const got=await chrome.storage.local.get(['config']); const c={...DEFAULTS,...(got.config||{})}; enabled.checked=!!c.enabled; operatorLabel.value=c.operatorLabel; quaiPayoutAddress.value=c.quaiPayoutAddress||''; reportUrl.value=c.reportUrl;}
async function saveConfig(){await chrome.storage.local.set({config:{enabled:enabled.checked,operatorLabel:operatorLabel.value.trim()||DEFAULTS.operatorLabel,quaiPayoutAddress:quaiPayoutAddress.value.trim(),reportUrl:reportUrl.value.trim()}}); saved.textContent=' saved'; setTimeout(()=>saved.textContent='',1500)}
save.onclick=saveConfig;
useOfficial.onclick=async()=>{reportUrl.value=OFFICIAL_REPORT_URL; await saveConfig();};
clearReport.onclick=async()=>{reportUrl.value=''; await saveConfig();};
load();
