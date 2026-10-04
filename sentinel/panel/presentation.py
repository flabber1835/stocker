"""Plain-language display only; never alter a financial or operational verdict."""
from __future__ import annotations

from sentinel.panel.model import Row, FINANCIAL_AUTHORITY_ROW_KEYS

_COPY = {
    'shadow_verification': ('Simulated portfolio check', 'Checks that the strategy portfolio was built correctly from the available market data. This is separate from your Alpaca account.'),
    'shadow_nav': ('Simulated portfolio value', 'The value of the strategy’s simulated shares and cash. This is not the balance in your Alpaca paper account.'),
    'shadow_return': ('Strategy gain or loss', 'The simulated strategy’s gain or loss since its starting book, excluding money added to a broker account.'),
    'paper_reconciliation': ('Paper account alignment', 'Checks whether Alpaca’s paper holdings and orders match the trading plan. Paper trading must be activated separately.'),
    'trial_verification': ('Paper account check', 'Checks the paper account’s holdings, cash and trading results. Unverified results should not be treated as confirmed performance.'),
    'actual_account': ('Paper account value', 'The value of simulated money held at Alpaca. No real-money trading takes place.'),
    'trial_return': ('Paper account gain or loss', 'The change in the paper account after accounting for deposits and withdrawals.'),
    'trial_drawdown': ('Fall from peak value', 'How far the paper account has fallen from its highest recorded value.'),
    'trial_annualized': ('Annualized paper return', 'An estimate of the yearly growth rate implied by the recorded paper results.'),
    'trial_intent': ('Next trading plan', 'What the system intends to hold. A plan is not proof that the broker has filled its orders.'),
    'ownership': ('Account connected to Sentinel', 'Shows whether Sentinel has been assigned control of a paper account. Shadow-only operation does not require paper trading.'),
    'feed': ('Market data', 'The latest trading day with accepted prices and company information. It should catch up before the next trading decision.'),
    'ingest': ('Data download', 'Shows the most recent attempt to download and prepare market data.'),
    'book': ('Strategy holdings', 'The stocks and cash chosen by Wealth Core. Initial formation simulates earlier sessions to build this portfolio before today.'),
    'exposure': ('Stock allocation', 'The fraction of the portfolio assigned to the stock strategy. The remaining allocation goes to the Treasury-bill sleeve.'),
    'terminals': ('Company events', 'Checks events such as delistings and acquisitions that can affect held shares.'),
    'broker': ('Paper holdings and orders', 'The broker account’s recorded holdings and order state. These are separate from the simulated strategy portfolio.'),
    'automation': ('Automatic paper trading', 'Shows whether scheduled paper trading is enabled. Disabled means the system will not submit paper orders.'),
    'automation_leader': ('Daily worker', 'Checks that one worker is responsible for the scheduled daily work.'),
    'automation_cycle': ('Today’s daily run', 'Tracks the daily sequence from preparing data to checking the paper account.'),
    'automation_alerts': ('System notifications', 'Messages queued when the system needs attention or completes an important step.'),
    'alert_dispatcher': ('Notification delivery', 'Checks that queued notifications can be delivered to your devices.'),
    'alpaca_account': ('Alpaca paper connection', 'Checks that the configured account is reachable and is a paper account.'),
    'backup_restore': ('Backup and recovery', 'Checks that a recent database backup can actually be restored and its portfolio verified.'),
    'runtime_identity': ('Installed software', 'Checks that the running software matches the reviewed release.'),
    'authority': ('Permission to trade', 'Shows whether this software and account have permission to submit paper orders. A working dashboard alone does not grant permission.'),
}

_STEPS = {
    'discovery': ('Start the daily run', 'Finds the next scheduled trading day and any unfinished work.'),
    'data': ('Update market data', 'Downloads and prepares the prices needed for the next decision.'),
    'open': ('Wait for market open', 'Waits for the trading session before sending the plan to Alpaca.'),
    'transport': ('Place paper orders', 'Sends the approved plan to the Alpaca paper account.'),
    'complete': ('Finish the daily run', 'Records the completed run after its checks finish.'),
    'refresh': ('Update market data', 'Downloads and accepts the prices needed for the next decision.'),
    'preflight': ('Check readiness', 'Checks data, software, backup and account prerequisites.'),
    'prepare': ('Calculate today’s plan', 'Updates the strategy portfolio and its stock allocation.'),
    'execute': ('Place paper orders', 'Sends the approved plan to the Alpaca paper account.'),
    'reconcile': ('Check shares and cash', 'Checks filled orders and account balances against the plan.'),
    'close': ('Finish daily accounting', 'Records the final result of the day’s paper run.'),
    'recover': ('Recover interrupted work', 'Resumes unfinished work without guessing whether an order was placed.'),
}


def describe(row: Row, status: str) -> tuple[str, str, str]:
    """Return display copy; caller retains row keys, raw evidence and status."""
    key = row.key
    copy = _COPY.get(key)
    if key.startswith('automation_step_'):
        copy = _STEPS.get(key.removeprefix('automation_step_'))
    label, explanation = copy or (row.label, row.detail)
    value = row.value
    if copy:
        value = (value.replace('TRIAL NOT VERIFIED', 'Paper account not verified')
                 .replace('TRIAL VERIFIED THROUGH', 'Paper account checked through')
                 .replace('SHADOW NOT VERIFIED', 'Simulated portfolio not verified')
                 .replace('SHADOW VERIFIED THROUGH', 'Simulated portfolio checked through')
                 .replace('PAPER NOT VERIFIED', 'Paper account not verified')
                 .replace('MIRROR CLEAN', 'Holdings and orders match')
                 .replace('NOT STARTED', 'Not started')
                 .replace('STATUS UNREADABLE', 'Unable to read status'))
        if status in {'fail', 'unknown'}:
            explanation += ' Attention needed: this check is failing or cannot be confirmed. Open the technical details for the recorded reason.'
        elif status == 'warn':
            explanation += ' This is waiting or needs review; it is not a completed check.'
        elif status == 'pending':
            explanation += ' This part has not started or is not enabled.'
    if key in FINANCIAL_AUTHORITY_ROW_KEYS and status != 'ok':
        explanation += ' This result is unverified; do not treat it as confirmed performance.'
    return label, value, explanation


CASINO_STAGE = '''<div class="casino-stage" aria-hidden="true">
  <div class="marquee-glow"></div>
  <span class="floating-chip chip-one">♠</span><span class="floating-chip chip-two">♥</span>
  <span class="floating-chip chip-three">♦</span>
  <svg class="hostess hostess-left" viewBox="0 0 100 240" focusable="false">
    <path fill="currentColor" d="M42 42Q31 13 38 3Q49 15 50 36Q57 8 66 3Q71 17 59 42Q69 47 68 62Q67 78 58 82L62 97Q85 108 78 123L67 116L63 143Q70 170 76 187L58 192L57 230L50 230L47 191L39 230L31 230L36 188L29 179Q41 149 38 126L24 146L19 142L29 112Q30 103 43 98L46 82Q33 76 33 60Q32 48 42 42Z"/>
    <path fill="#e6b965" d="M43 97L51 103L61 97L59 111L51 106L44 111Z"/>
  </svg>
  <svg class="hostess hostess-right" viewBox="0 0 100 240" focusable="false">
    <path fill="currentColor" d="M45 32Q35 11 40 1Q52 12 53 29Q61 8 67 5Q73 18 62 36Q75 45 72 61Q71 76 59 82L60 98Q79 102 85 120L89 139L84 142L69 119L65 146L78 186L58 192L60 231L52 231L46 194L40 231L32 231L36 190L24 185L39 145L36 119L21 135L17 130L28 108Q32 101 43 97L46 82Q31 75 32 57Q29 41 45 32Z"/>
    <path fill="#e6b965" d="M44 99L51 105L62 98L60 113L51 108L44 114Z"/>
  </svg>
</div>'''

CASINO_ACCENT = '''<div class="casino-accent" aria-hidden="true">
  <span class="reel"><span>♠<br>♥<br>♦<br>♠</span></span>
  <span class="reel"><span>♦<br>♣<br>♥<br>♦</span></span>
  <span class="reel"><span>♣<br>♠<br>♦<br>♣</span></span>
  <span class="accent-caption">THE DAILY TABLE</span>
</div>'''

CASINO_CSS = '''
:root,:root[data-theme="dark"],:root[data-theme="light"]{
 --bg:#0e0e19;--card:#1b1c2b;--ink:#faf4e8;--muted:#c5bdaf;--line:#494338;
 --ok:#80e4b2;--warn:#ffcb78;--fail:#ff918b;--pending:#c0bfd3;
 --okbg:#193a30;--warnbg:#40331f;--failbg:#452626;--pendingbg:#2d2c3c;
 --shadow:0 14px 36px #0004;
}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --bg:#0e0e19;--card:#1b1c2b;--ink:#faf4e8;--muted:#c5bdaf;--line:#494338;
 --ok:#80e4b2;--warn:#ffcb78;--fail:#ff918b;--pending:#c0bfd3;
}}
body{background:radial-gradient(ellipse at 12% 0%,#59345388,transparent 45%),
 radial-gradient(ellipse at 95% 35%,#193b4b99,transparent 45%),#0e0e19;min-height:100vh}
.wrap{position:relative;z-index:1;max-width:620px}
header{padding:20px 18px;border:1px solid #a7844655;border-radius:22px;
 background:linear-gradient(125deg,#292039ef,#141723ef);box-shadow:0 8px 40px #0005}
h1{font-size:20px;letter-spacing:.16em;color:#f7d78c;font-family:Georgia,serif}
.brand img{border:1px solid #bd9355;width:48px;height:48px}
.row,.push-card,details{background:linear-gradient(135deg,#222333f5,#171926f5);border-color:#494338}
.row{border-left:3px solid #9f7c40;padding:17px 18px;border-radius:17px}
.row.fail,.row.unknown{border-left-color:var(--fail)}
.row.warn{border-left-color:var(--warn)}.row.ok{border-left-color:var(--ok)}
.label{color:#e2c68c;letter-spacing:.06em}.value{font-size:22px}.detail{line-height:1.6;margin-top:3px}
.row .technical{grid-column:2;margin:7px 0 0;background:transparent;border:0;box-shadow:none}
.technical summary{padding:0;color:#bcb1c5;font-size:12px;font-weight:400}
.technical .detail-body{padding:8px 0 0;font-size:12px;overflow-wrap:anywhere;color:var(--muted)}
.mode-guide{margin:16px 2px;color:#d5ccbd;font-size:14px;line-height:1.7}
.mode-guide strong{color:#f7d78c}.mode-guide p{margin:7px 0}
button{background:linear-gradient(135deg,#f1d48e,#b38b47);color:#18151d;border-color:#b38b47}
button.secondary{color:#f7d78c}button:focus-visible,summary:focus-visible{outline:3px solid #f7d78c;outline-offset:3px}
.casino-stage{position:fixed;inset:0;pointer-events:none;overflow:hidden;z-index:0}
.marquee-glow{position:absolute;inset:10px;border:6px dotted #c89a53;border-radius:26px;opacity:.38;animation:marquee 3s ease-in-out infinite}
.floating-chip{position:absolute;width:66px;height:66px;display:grid;place-items:center;
 border:7px dashed #f1d593;border-radius:50%;background:#73394b;color:#f7e9b5;font:26px Georgia,serif;
 box-shadow:0 0 0 3px #ba8d51,0 12px 30px #0006;opacity:.48;animation:chip-drift 15s ease-in-out infinite}
.chip-one{left:6%;top:26%}.chip-two{right:6%;top:53%;animation-delay:-5s;background:#315865}
.chip-three{left:9%;top:80%;animation-delay:-9s;background:#50406c}
.hostess{position:absolute;width:125px;height:300px;color:#c99a6255;bottom:7%;filter:drop-shadow(0 0 25px #f6b97833)}
.hostess-left{left:max(0px,calc(50% - 470px))}.hostess-right{right:max(0px,calc(50% - 470px));transform:scaleX(-1)}
.casino-accent{display:flex;align-items:center;gap:5px;margin-top:15px;color:#e4c789}
.reel{height:28px;width:27px;overflow:hidden;border:1px solid #a77c47;border-radius:5px;background:#ede4c9;color:#593246;text-align:center;line-height:28px;font:20px/28px Georgia,serif}
.reel>span{display:block;animation:reel-turn 18s ease-in-out infinite}.reel:nth-child(2)>span{animation-delay:-6s}.reel:nth-child(3)>span{animation-delay:-12s}
.accent-caption{font-size:10px;letter-spacing:.2em;margin-left:7px}
@keyframes marquee{50%{opacity:.7}}
@keyframes chip-drift{50%{transform:translateY(-22px) rotate(30deg)}}
@keyframes reel-turn{0%,40%{transform:translateY(0)}50%,90%{transform:translateY(-56px)}100%{transform:translateY(-84px)}}
@media(max-width:760px){.hostess{width:80px;height:192px;opacity:.4}.floating-chip{opacity:.16}.marquee-glow{inset:4px;opacity:.25}.wrap{max-width:620px}}
@media(prefers-reduced-motion:reduce){.casino-stage *, .casino-accent *{animation:none!important}}
'''
