"""The current mobile presentation; one palette and no decorative animation."""

CSS = r"""
:root,:root[data-theme="dark"],:root[data-theme="light"]{
 --bg:#16111f;--card:#241c30;--ink:#f5eee3;--muted:#c2b7c8;--line:#4d3c57;
 --ok:#8ce0b4;--warn:#f2cd83;--fail:#ffa69e;--pending:#c4bfd1;
 --okbg:#20392f;--warnbg:#493b23;--failbg:#492c32;--pendingbg:#30283c;
 --shadow:0 8px 28px #0002;
}
*{box-sizing:border-box}
body{margin:0;color:var(--ink);font:15px/1.45 ui-sans-serif,-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,sans-serif;
 -webkit-text-size-adjust:100%;background:radial-gradient(ellipse at 50% 0%,#342039 0,transparent 52%),#16111f;
 padding:max(18px,env(safe-area-inset-top)) max(14px,env(safe-area-inset-right))
 max(24px,env(safe-area-inset-bottom)) max(14px,env(safe-area-inset-left));min-height:100vh}
.wrap{position:relative;z-index:1;max-width:760px;margin:0 auto}
header{display:block;padding:6px 0 0;margin:0 0 18px}
.brand{display:flex;align-items:center;gap:12px}
.brand img{width:42px;height:42px;border-radius:11px;border:1px solid #a98750;flex:0 0 auto}
h1{font-family:Georgia,serif;font-size:clamp(16px,4.9vw,25px);font-weight:650;margin:0;
 letter-spacing:.11em;color:#eacb8e;line-height:1.2}
.brand-subtitle{font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--muted);margin-top:5px}
.state{display:block;border:1px solid currentColor;border-radius:12px;font-size:12px;font-weight:650;
 letter-spacing:.045em;padding:12px 14px;margin-top:19px;line-height:1.4;overflow-wrap:anywhere}
.state.ok{background:var(--okbg);color:var(--ok)}.state.warn{background:var(--warnbg);color:var(--warn)}
.state.fail,.state.unknown{background:var(--failbg);color:var(--fail)}.state.pending{background:var(--pendingbg);color:var(--pending)}
.heartbeat{display:block;margin:9px 2px 0;color:var(--muted);font-size:11px;
 font-variant-numeric:tabular-nums;letter-spacing:0;line-height:1.5}
.heartbeat::before{content:"\25CF";color:var(--ok);margin-right:7px}
.not-current .heartbeat{color:var(--fail);font-weight:650}.not-current .heartbeat::before{color:var(--fail)}
.status-reasons{margin-top:12px;padding:0 3px;font-size:13px;line-height:1.5}
.status-reasons ul{margin:6px 0;padding-left:19px}.status-reasons a{color:var(--fail)}
.err{background:var(--failbg);color:var(--fail);border-radius:12px;padding:12px 14px;margin-bottom:12px;font-size:13px}
.row{background:linear-gradient(135deg,#222333f5,#171926f5);border:1px solid #494338;border-left:3px solid #9f7c40;
 border-radius:17px;padding:17px 18px;margin-bottom:10px;box-shadow:var(--shadow);
 display:grid;grid-template-columns:18px 1fr;gap:2px 11px}
.row.fail,.row.unknown{border-left-color:var(--fail)}.row.warn{border-left-color:var(--warn)}.row.ok{border-left-color:var(--ok)}
.dot{grid-row:1/span 3;font-size:13px;line-height:1.5;text-align:center}
.dot.ok{color:var(--ok)}.dot.warn{color:var(--warn)}.dot.fail,.dot.unknown{color:var(--fail)}.dot.pending{color:var(--pending)}
.label{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:#e2c68c}
.value{font-size:22px;font-weight:600;line-height:1.3;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.row.fail .value{color:var(--fail)}.detail{font-size:13px;color:var(--muted);overflow-wrap:anywhere;line-height:1.6;margin-top:3px}
.age{font-size:11px;color:var(--muted);margin-top:3px}.age.stale{color:var(--warn);font-weight:600}
footer code{font-size:11px}
details{background:linear-gradient(135deg,#222333f5,#171926f5);border:1px solid #494338;border-radius:14px;
 margin:10px 0;box-shadow:var(--shadow);overflow:hidden}
summary{cursor:pointer;padding:13px 15px;font-weight:650;list-style-position:inside}
.detail-body{padding:0 15px 14px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}
th,td{padding:7px 6px;text-align:left;border-top:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;letter-spacing:.04em}
.portfolio-table{min-width:650px;table-layout:auto;overflow-wrap:normal}
.portfolio-table th,.portfolio-table td{white-space:nowrap;word-break:normal}
.row .technical{grid-column:2;margin:7px 0 0;background:transparent;border:0;box-shadow:none}
.technical summary{padding:0;color:#bcb1c5;font-size:12px;font-weight:400}
.technical .detail-body{padding:8px 0 0;font-size:12px;overflow-wrap:anywhere;color:var(--muted)}
.mode-guide{margin:16px 2px;color:#d5ccbd;font-size:14px;line-height:1.7}.mode-guide strong{color:#f7d78c}.mode-guide p{margin:7px 0}
.not-current .row.ok{border-color:var(--fail)}.not-current .dot.ok{color:var(--fail)}
.refreshing-status .row.ok{border-color:var(--warn)}
.refreshing-status .dot.ok,.refreshing-status .heartbeat{color:var(--warn)}.refreshing-status .heartbeat::before{color:var(--warn)}
.refreshing-status .row.ok .value::before{content:"LAST KNOWN \00B7 ";color:var(--warn)}
.push-card{background:linear-gradient(135deg,#222333f5,#171926f5);border:1px solid #494338;border-radius:14px;
 padding:13px 15px;margin:10px 0;box-shadow:var(--shadow)}
.push-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
button{appearance:none;border:1px solid #b38b47;border-radius:10px;background:linear-gradient(135deg,#f1d48e,#b38b47);
 color:#18151d;font:inherit;font-weight:650;min-height:44px;padding:9px 13px;cursor:pointer}
button.secondary{background:transparent;color:#f7d78c}button[hidden]{display:none}
#push-status{font-size:13px;color:var(--muted);overflow-wrap:anywhere}
@media(max-width:360px){body{font-size:14px}.row{padding:12px}.value{font-size:16px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation:none!important}}
.overview{display:grid;gap:14px}.overview-card{min-width:0;background:linear-gradient(135deg,#2c2336,#211a2b);
 border:1px solid #56435c;border-radius:17px;padding:20px;box-shadow:var(--shadow)}
.overview-heading{display:flex;gap:12px;align-items:center;justify-content:space-between;min-width:0}
.overview h2{font-family:Georgia,serif;font-size:23px;font-weight:400;color:#f2e5cb;margin:0;line-height:1.25}
.overview-eyebrow{margin:0 0 5px;color:#cdb899;font-size:10px;letter-spacing:.15em;text-transform:uppercase}
.overview-tag{font-size:10px;color:#e5c68c;border:1px solid #806348;border-radius:6px;padding:4px 7px;
 flex:0 0 auto;max-width:47%;overflow-wrap:anywhere;letter-spacing:.055em}
.plan-schedule{display:flex;justify-content:space-between;gap:12px;margin:17px 0 0;font-size:12px;color:var(--muted);
 flex-wrap:wrap}.plan-schedule strong{color:#eddfca;font-weight:600}.plan-legs{list-style:none;margin:12px 0;padding:0}
.plan-leg{border-top:1px solid var(--line);padding:14px 0 12px}.plan-leg-main{display:grid;
 grid-template-columns:minmax(60px,1fr) auto minmax(78px,auto);align-items:center;gap:10px}
.plan-ticker{font-size:21px;font-weight:650;overflow-wrap:anywhere}.plan-action{font-size:10px;text-transform:uppercase;
 padding:4px 8px;border-radius:5px;letter-spacing:.05em;color:var(--pending);background:var(--pendingbg)}
.plan-leg.buy .plan-action{color:var(--ok);background:var(--okbg)}
.plan-leg.sell .plan-action{color:#ffb2ab;background:#492f37}
.plan-quantity{font-size:14px;text-align:right;font-weight:550;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.plan-leg-basis{font-size:11px;color:var(--muted);margin-top:4px;font-variant-numeric:tabular-nums}
.plan-outcome{border-left:2px solid #bb904d;background:#3b2d29;padding:9px 10px;margin-top:11px;
 color:#f1cc8d;font-size:12px;line-height:1.5}.no-plan-changes{color:var(--muted);font-size:14px;padding:10px 0}
.overview-note,.overview-evidence{font-size:11px;line-height:1.6;color:var(--muted);margin:9px 0 0;overflow-wrap:anywhere}
.run-progress{font-size:12px;line-height:1.6;color:#e7d7b9;margin:8px 0}
.not-current .run-progress{color:var(--fail)}
.refreshing-status .run-progress,.retained-overview .run-progress{color:var(--warn)}
.overview-evidence{font-size:10px}.overview-inline-details{background:none;border:0;border-radius:0;box-shadow:none;margin:4px 0 0}
.overview-inline-details summary{padding:0;font-size:10px;font-weight:400;text-decoration:underline;color:inherit}
.overview-inline-details .detail-body{padding:7px 0 0;color:var(--muted);font-size:10px;overflow-wrap:anywhere}
.overview-disclosure{border:0;border-top:1px solid var(--line);border-radius:0;background:none;box-shadow:none;margin:14px 0 0}
.overview-disclosure summary{padding:12px 0 0;color:#e7c88f;font-size:12px;font-weight:500}
.overview-disclosure summary span{float:right;color:var(--muted)}.overview-disclosure .detail-body{padding:12px 0 0}
.overview-table-scroll{overflow-x:auto}.overview table{min-width:350px}.overview th,.overview td{font-size:11px}
.overview td{white-space:nowrap}.account-overview{padding:16px 20px}.account-overview h2{font-size:17px}
.account-stats{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:14px}
.account-stats>div+div{border-left:1px solid var(--line);padding-left:20px}
.account-stats span{font-size:11px;color:var(--muted);display:block}.account-stats strong{font-size:24px;
 font-weight:550;display:block;margin-top:3px;font-variant-numeric:tabular-nums;letter-spacing:-.02em;overflow-wrap:anywhere}
.slot-counts{display:flex;flex-wrap:wrap;gap:7px 15px;font-size:11px;color:var(--muted);margin:12px 0 15px}
.slot-counts span:first-child{color:#bfe1c9}.slot-grid{list-style:none;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
 gap:9px;padding:0;margin:0}.slot-tile{min-width:0;display:flex;flex-direction:column;align-items:flex-start;
 background:#30263b;border:1px solid #5a485e;border-radius:10px;padding:11px 10px;min-height:120px}
.slot-tile.occupied{border-top:2px solid #8caf91}.slot-tile.exit-pending{border-top-color:#df9a94}
.slot-tile.cooling{background:#2a2433;border-style:dashed;border-color:#665140}
.slot-tile.reserved{border-top:2px solid #baafdb}.slot-tile.ready{border-color:#8caf91}
.slot-number{font-size:9px;color:#baacc3;text-transform:uppercase;letter-spacing:.07em}
.slot-main{font-size:22px;line-height:1.25;font-weight:550;margin:7px 0 3px;overflow-wrap:anywhere;max-width:100%}
.slot-tile.cooling .slot-main{color:#edcb89}.slot-tile.ready .slot-main{color:var(--ok);font-size:20px}
.slot-state{font-size:10px;line-height:1.35;color:#d0c4d5}.exit-pending .slot-state{color:#ffb2ab}
.slot-evidence{margin:8px 0 0;border:0;border-radius:0;background:none;box-shadow:none;overflow:visible;width:100%}
.slot-evidence summary{padding:0;font-size:9px;font-weight:400;color:#bbadbd}
.slot-evidence>div{font-size:10px;line-height:1.5;color:var(--muted);padding-top:7px;overflow-wrap:anywhere}
.overview-unavailable{color:var(--warn);font-size:14px;margin:14px 0 0}
.overview-history,.overview-retained,.overview-withdrawn{font-size:12px;line-height:1.5;margin:0;
 color:var(--warn);padding:10px 12px;background:var(--warnbg);border-radius:8px}
.overview-history{margin-bottom:12px}.overview-withdrawn{display:none}
.not-current .overview-withdrawn{display:block;color:var(--fail);background:var(--failbg)}
.not-current .overview-card{border-color:var(--fail)}
.not-current .overview-card h2::after{content:" · LAST KNOWN";font:10px ui-sans-serif,sans-serif;color:var(--fail)}
.not-current .plan-action,.not-current .plan-leg.buy .plan-action,.not-current .overview-tag,
 .not-current .slot-state,.not-current .slot-tile.ready .slot-main,.not-current .slot-counts span:first-child{color:var(--fail)}
.refreshing-status .overview-withdrawn{display:block;color:var(--warn);background:var(--warnbg)}
.refreshing-status .overview-card{border-color:#9a7949}
.refreshing-status .overview-card h2::after{content:" · LAST KNOWN";font:10px ui-sans-serif,sans-serif;color:var(--warn)}
.retained-overview .overview-card{border-color:#9a7949}
.retained-overview .overview-card h2::after{content:" · LAST KNOWN";font:10px ui-sans-serif,sans-serif;color:var(--warn)}
.refreshing-status .slot-tile,.refreshing-status .slot-tile.occupied,.refreshing-status .slot-tile.ready,
 .retained-overview .slot-tile,.retained-overview .slot-tile.occupied,.retained-overview .slot-tile.ready{border-color:#9a7949}
.refreshing-status .plan-leg.buy .plan-action,.refreshing-status .slot-tile.ready .slot-main,
 .refreshing-status .slot-counts span:first-child,.retained-overview .plan-leg.buy .plan-action,
 .retained-overview .slot-tile.ready .slot-main,.retained-overview .slot-counts span:first-child{color:var(--warn)}
.not-current .slot-tile,.not-current .slot-tile.occupied,.not-current .slot-tile.ready{border-color:var(--fail)}
.not-current .plan-leg.buy .plan-action,.not-current .slot-tile.ready .slot-main,
 .not-current .slot-counts span:first-child{color:var(--fail)}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
#system-details{margin-top:18px;background:#201a29;border-color:#493c51;border-radius:13px}
#system-details>summary{padding:15px 17px;color:#cbbcce;font-size:13px;font-weight:500}
#system-details>.detail-body{padding:0 12px 12px;overflow:visible}#system-details .mode-guide{margin-top:0;font-size:12px}
#system-details .row{padding:14px 13px;background:#261f30;border-radius:11px;border-color:#493c51}
#system-details .value{font-size:17px}#system-details .label{font-size:10px}
#system-details .detail{font-size:12px;line-height:1.5}#system-details .push-card{background:#261f30}
button:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid #f4d79b;outline-offset:3px}
footer{font-size:10px;color:#b5a8be;line-height:1.7;margin-top:18px}footer>.technical{font-size:10px;background:none;border:0;box-shadow:none}
footer>.technical>summary{font-size:10px;font-weight:400;padding:4px}
@media(min-width:600px){.overview-card{padding:23px}.slot-grid{gap:12px}.slot-tile{min-height:127px;padding:14px}.slot-main{font-size:26px}}
@media(max-width:420px){.overview-card{padding:17px 14px}.overview h2{font-size:21px}.account-overview h2{font-size:16px}
 .account-stats strong{font-size:22px}.slot-grid{gap:7px}.slot-tile{padding:10px 7px}.slot-main{font-size:20px}
 .overview-heading{gap:8px}.overview-tag{font-size:9px;padding:4px 5px}.plan-leg-main{gap:7px}}
@media(max-width:360px){.slot-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.slot-tile{min-height:115px;padding:12px}
 .slot-main{font-size:24px}.overview h2{font-size:20px}.account-overview h2{font-size:16px}.account-stats strong{font-size:21px}
 .account-stats>div+div{padding-left:14px}.account-stats{gap:10px}.plan-ticker{font-size:19px}.plan-quantity{font-size:13px}}
"""
