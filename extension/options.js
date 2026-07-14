const DEFAULTS={enabled:true,reportUrl:'',operatorLabel:'anonymous-sensor'};
async function load(){const got=await chrome.storage.local.get(['config']); const c={...DEFAULTS,...(got.config||{})}; enabled.checked=!!c.enabled; operatorLabel.value=c.operatorLabel; reportUrl.value=c.reportUrl;}
save.onclick=async()=>{await chrome.storage.local.set({config:{enabled:enabled.checked,operatorLabel:operatorLabel.value.trim()||DEFAULTS.operatorLabel,reportUrl:reportUrl.value.trim()}}); saved.textContent=' saved'; setTimeout(()=>saved.textContent='',1500)};
load();
