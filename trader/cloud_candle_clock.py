"""Client-side UTC/Warsaw clock and candle countdown.

A clock must keep ticking even if the REST API, Supabase or the main
Streamlit fragment is temporarily slow. This is DEVICE time for display,
NOT proof of a new broker quote, trade or closed candle.
"""
from __future__ import annotations

import streamlit.components.v1 as components

SECONDS={"M1":60,"M2":120,"M5":300,"M15":900,"H1":3600}


def render_candle_clock(choice="M1"):
    if choice not in SECONDS:
        raise ValueError("Invalid display clock timeframe")
    # Whitelisted seconds only; JS has no dynamic user-controlled strings.
    duration=SECONDS[choice]
    html="""<!doctype html><html><head><meta charset="utf-8">
<style>
body{margin:0;background:transparent;color:#dceaff;font:600 13px system-ui,sans-serif}
.wrap{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;padding:4px 1px}
.value{color:#63dcff;font-variant-numeric:tabular-nums}
.small{color:#9babca;font-size:11px;font-weight:400}
</style></head><body>
<div class="wrap">
 <div>🕒 Polska: <span class="value" id="warsaw">--:--:--</span></div>
 <div>UTC: <span class="value" id="utc">--:--:--</span></div>
 <div>⏳ Koniec świecy: <span class="value" id="left">--:--</span></div>
 <span class="small">Zegar urządzenia, nie potwierdzenie nowej ceny</span>
</div>
<script>
(function(){
 const dur=__SECONDS__*1000;
 const pl=new Intl.DateTimeFormat('pl-PL',
   {timeZone:'Europe/Warsaw',hour:'2-digit',minute:'2-digit',
    second:'2-digit',hour12:false});
 function update(){
   const now=Date.now(),date=new Date(now);
   document.getElementById('warsaw').textContent=pl.format(date);
   document.getElementById('utc').textContent=date.toISOString().slice(11,19);
   let left=dur-(now%dur);
   const seconds=Math.ceil(left/1000);
   document.getElementById('left').textContent=
      String(Math.floor(seconds/60)).padStart(2,'0')+':'+
      String(seconds%60).padStart(2,'0');
 }
 update();setInterval(update,500);
})();
</script></body></html>""".replace("__SECONDS__",str(duration))
    components.html(html,height=49,scrolling=False)
