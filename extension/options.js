const DEFAULTS={enabled:true,reportUrl:'',operatorLabel:'anonymous-sensor',quaiPayoutAddress:''};
async function load(){const got=await chrome.storage.local.get(['config']); const c={...DEFAULTS,...(got.config||{})}; enabled.checked=!!c.enabled; operatorLabel.value=c.operatorLabel; quaiPayoutAddress.value=c.quaiPayoutAddress||''; reportUrl.value=c.reportUrl;}
save.onclick=async()=>{await chrome.storage.local.set({config:{enabled:enabled.checked,operatorLabel:operatorLabel.value.trim()||DEFAULTS.operatorLabel,quaiPayoutAddress:quaiPayoutAddress.value.trim(),reportUrl:reportUrl.value.trim()}}); saved.textContent=' saved'; setTimeout(()=>saved.textContent='',1500)};
load();
