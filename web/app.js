const $ = id => document.getElementById(id);
const state = {mode: 'live', category: 'C', defenseSort: 'matchup_delta_per_30', data: null, request: 0, visible:12, positionSort:null, positionDirection:'desc', squad:null, squadRequest:0, selectedPlan:0, squadKeep:[], squadKeepInitialized:false};
const fmt = (value, digits = 1) => value == null ? '—' : Number(value).toLocaleString('he-IL', {maximumFractionDigits: digits});
const sign = (value,digits=1) => value == null ? '—' : `${value > 0 ? '+' : ''}${fmt(value,digits)}`;
const date = value => value ? new Date(value).toLocaleString('he-IL', {timeZone: 'Asia/Jerusalem', dateStyle: 'short', timeStyle: 'short'}) : 'אין עדכון';
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const numeric = value => `<span class="numeric">${fmt(value)}</span>`;
const confidence = value => `<span class="confidence ${escape(value)}"><i></i><i></i><i></i> ${{low:'קטן',medium:'בינוני',higher:'גדול יותר'}[value]}</span>`;

const displayName = name => {
  const parts=String(name||'').split(',');
  return parts.length===2 ? `${parts[1].trim()} ${parts[0].trim()}` : String(name||'');
};
function imageUrl(value) {
  try {
    const url=new URL(value);
    if(url.protocol==='https:' && ['media-cdn.incrowdsports.com','media-cdn.cortextech.io','fantaking-assets.dunkest.com','www.dunkest.com'].includes(url.hostname) && !url.username && !url.password && (!url.port||url.port==='443'))return url.href;
  }catch{}
  return null;
}
function portrait(p, className='portrait') {
  const src=imageUrl(p.image_url);
  return `<img class="${className}${src?'':' placeholder'}" data-portrait src="${escape(src||'/player-placeholder.svg')}" alt="${src?escape(displayName(p.name)):''}" width="100" height="112" loading="lazy" decoding="async" referrerpolicy="no-referrer">`;
}
function priceBadge(p) {
  if(p.credits!=null)return `<span class="credit-badge" title="${escape(`עודכן ${date(p.price_as_of)}`)}"><b>${fmt(p.credits)}</b><span>קרדיטים</span></span>`;
  if(p.reported_credits!=null)return `<span class="credit-badge stale" title="${escape(`המחיר האחרון שדווח: ${date(p.price_as_of)}; אינו מאומת למחזור הנבחר`)}"><b>${fmt(p.reported_credits)}</b><span>מחיר קודם</span></span>`;
  return '<span class="credit-badge missing"><span>מחיר טרם חובר</span></span>';
}
document.addEventListener('error',event=>{
  const img=event.target;
  if(img instanceof HTMLImageElement && img.hasAttribute('data-portrait') && !img.src.endsWith('/player-placeholder.svg')){
    img.src='/player-placeholder.svg';img.classList.add('placeholder');img.alt='';
  }
},true);

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

function feedback(message, error = false) {
  $('feedback').textContent = message;
  $('feedback').className = `notice${error ? ' error' : ''}${message ? '' : ' hidden'}`;
}

async function load() {
  const request = ++state.request;
  const params = new URLSearchParams({mode:state.mode, window:$('window').value, venue:$('venue').value});
  if ($('round').value) params.set('round', $('round').value);
  try {
    const data = await api(`/api/dashboard?${params}`);
    if (request !== state.request) return;
    state.data = data;
    $('data').classList.toggle('hidden',!!data.public_read_only);
    const selected = $('round').value;
    $('round').innerHTML = '<option value="">המחזור הבא</option>' + data.rounds.map(r => `<option value="${r}">${r}</option>`).join('');
    $('round').value = selected;
    $('round-number').textContent = data.target_round ?? '—';
    $('season-label').textContent = data.season === 'DEMO' ? 'DEMO / SYNTHETIC' : data.season;
    $('season').value = data.season === 'DEMO' ? 'E2026' : data.season;
    $('stat-games').textContent = fmt(data.coverage.games_with_stats, 0);
    $('stats-coverage').textContent = `מתוך ${data.coverage.games} משחקים שהושלמו לפני המחזור`;
    $('stat-players').textContent = fmt(data.coverage.players, 0);
    $('positions-coverage').textContent = `${data.coverage.known_positions} עם עמדה; ${data.coverage.detailed_guard_roles} גארדים עם פירוט תפקיד`;
    $('stat-prices').textContent = fmt(data.coverage.fresh_prices, 0);
    $('stat-status').textContent = fmt(data.coverage.fresh_availability, 0);
    $('updated').textContent = `הניתוח חושב: ${date(data.generated_at)}`;
    $('empty').classList.toggle('hidden', data.coverage.appearances > 0);
    $('demo-banner').classList.toggle('hidden', state.mode !== 'demo');
    $('mode-label').textContent = state.mode === 'demo' ? 'הדגמה סינתטית' : 'מקורות אמיתיים';
    $('mode-toggle').textContent = state.mode === 'demo' ? 'חזור לנתונים אמיתיים' : 'הצג הדגמה';
    $('data-mode').textContent = state.mode === 'demo' ? 'DEMO DATA' : 'LIVE DATA';
    $('source-list').textContent = data.sources.length ? data.sources.join(' · ') : 'עדיין אין מקורות';
    $('export-download').href = `/api/export?mode=${state.mode}`;
    $('roster-download').href = `/api/roster-template?mode=${state.mode}`;
    $('sync-button').disabled = state.mode === 'demo';
    $('roster-button').disabled = state.mode === 'demo';
    renderScout();
    loadSquad();
    renderDefense();
    renderPlayers();
    loadValidation(request);
  } catch (error) { feedback(`לא ניתן לטעון את הניתוח: ${error.message}`, true); }
}

async function loadValidation(request) {
  try {
    const [report,market] = await Promise.all([api(`/api/backtest?mode=${state.mode}`),api('/api/market-status')]);
    if (request !== state.request) return;
    $('market-sync').disabled = state.mode === 'demo' || !market.credential_present;
    $('market-connection').textContent = market.last_import ? `עודכנו ${market.last_import.matched} מחירים; ${market.last_import.unmatched} שחקנים לא הותאמו.` : market.credential_present ? 'קיימת הרשאה לבדיקה; החיבור החי עדיין לא אומת.' : 'מקור המחירים: EuroLeague Fantasy Challenge. נדרש חיבור מורשה; אפשר גם לייבא CSV.';
    const available = report.available && report.summary.n > 0;
    $('validation-metrics').classList.toggle('hidden',!available);
    $('validation-rounds').classList.toggle('hidden',!available);
    $('backtest-download').classList.toggle('hidden',!available);
    $('backtest-download').href = `/api/backtest/export?mode=${state.mode}`;
    if (!available) {
      $('validation-message').textContent = 'עדיין אין דוח עם מספיק תחזיות היסטוריות להשוואה. אין כרגע הוכחה שההתאמה ליריבה משפרת את החיזוי.';
      return;
    }
    const tested = report.segments.holdout;
    const sample = tested.n ? tested : report.summary;
    $('evaluation-n').textContent = fmt(sample.n,0);
    $('evaluation-split').textContent = tested.n ? `מחזורים ${report.holdout_rounds.join(', ')}` : 'מדגם כולל; אין מדגם נפרד מספיק';
    $('baseline-mae').textContent = fmt(sample.baseline_mae,2);
    $('model-mae').textContent = fmt(sample.model_mae,2);
    $('evaluation-gain').textContent = sign(sample.mae_improvement,3);
    const conclusion = sample.mae_improvement > 0 ? 'במדגם הזה התאמת היריבה הפחיתה את השגיאה.' : 'במדגם הזה התאמת היריבה לא שיפרה את השגיאה. אין לראות בתחזית יתרון מוכח.';
    const interval=sample.mae_improvement_ci95 ? ` טווח השיפור האמפירי (95%): ${sign(sample.mae_improvement_ci95[0],3)} עד ${sign(sample.mae_improvement_ci95[1],3)} PIR, בדגימה חוזרת של משחקים.` : '';
    $('validation-message').textContent = `${state.mode === 'demo' ? 'בדיקה סינתטית להדגמה בלבד.' : `עונה ${report.season}; מחזורים עד ${report.through_round}.`} ${conclusion}${interval} ${report.coverage.missing_prediction} הופעות היו ללא מספיק נתונים לתחזית.`;
    $('evaluation-rows').innerHTML = report.by_round.filter(r=>r.n).map(r=>`<tr><td>${r.round}</td><td>${r.n}</td><td>${numeric(r.baseline_mae)}</td><td>${numeric(r.model_mae)}</td><td><span class="numeric effect ${r.mae_improvement<0?'negative':''}">${sign(r.mae_improvement,3)}</span></td><td>${r.segment==='holdout'?'בדיקה נפרדת':'מדגם מוקדם'}</td></tr>`).join('');
  } catch(error) {
    if (request===state.request) $('validation-message').textContent = `דוח הבדיקה לא נטען: ${error.message}`;
  }
}

function renderDefense() {
  if (!state.data) return;
  const rows = state.data.defenses.filter(r => r.category === state.category);
  rows.sort((a,b) => (b[state.defenseSort] ?? -Infinity) - (a[state.defenseSort] ?? -Infinity));
  const missing = state.category==='PG' && state.data.coverage.players ? 'המקור הרשמי מאגד רכזים וקלעים כגארדים. אפשר לצפות בלשונית הגארדים; ניתוח רכזים בלבד דורש מיפוי תפקידים מפורט.' : 'אין עדיין נתונים לעמדה ולטווח שנבחרו.';
  $('defense-rows').innerHTML = rows.length ? rows.map((r,i) => `<tr><td><span class="team-name"><span class="team-badge">${String(i+1).padStart(2,'0')}</span>${escape(r.team)}</span></td><td>${numeric(r.average_pir)}</td><td>${numeric(r.pir_per_30)}</td><td><span class="numeric effect ${r.matchup_delta_per_30 == null ? 'neutral' : r.matchup_delta_per_30 < 0 ? 'negative' : ''}">${sign(r.matchup_delta_per_30)}</span></td><td>${r.games} <small class="confidence">/ ${r.comparable_games} להשוואה</small></td><td>${confidence(r.confidence)}</td></tr>`).join('') : `<tr><td colspan="6" class="no-results">${missing}</td></tr>`;
}

function renderPlayers() {
  if (!state.data) return;
  let players = state.data.recommendations.filter(r => r.category === state.category);
  if ($('eligible-only').checked) players = players.filter(r => r.eligible);
  const maxPrice = $('max-price').value;
  if (maxPrice !== '') players = players.filter(r => r.credits != null && r.credits <= Number(maxPrice));
  const search = $('player-search').value.trim().toLocaleLowerCase();
  if (search) players = players.filter(r => `${r.name} ${r.team} ${r.opponent}`.toLocaleLowerCase().includes(search));
  const key = $('ranking').value;
  players.sort((a,b) => (b[key] ?? -Infinity) - (a[key] ?? -Infinity));
  $('candidate-count').textContent = `${players.length} מועמדים`;
  $('show-more').classList.toggle('hidden', players.length <= 12);
  $('show-more').textContent = state.visible === 12 ? `הצג את כל ${players.length} המועמדים` : 'הצג רק 12 מועמדים מובילים';
  $('player-cards').innerHTML = players.length ? players.slice(0,state.visible).map((p,i) => `<article class="player-card ${i === 0 && p.eligible ? 'top-pick' : ''}">
    <div class="player-header">${portrait(p,'player-avatar')}<div><h3 dir="auto">${escape(displayName(p.name))}</h3><small>${escape(p.team)}</small></div><span class="position-chip">${escape(p.position)}</span></div>
    <div class="opponent-line">מול <b>${escape(p.opponent)}</b> · ${p.venue === 'home' ? 'בית' : 'חוץ'} · ${escape(date(p.date))}</div>
    <div class="prediction"><div><span>תחזית PIR</span><strong>${fmt(p.projected_pir)}</strong></div><div class="boost"><span>יתרון היריבה</span><strong class="${p.matchup_delta < 0 ? 'negative' : ''}">${sign(p.matchup_delta)}</strong></div></div>
    <div class="player-details">${priceBadge(p)}<span>PIR לקרדיט <b>${fmt(p.pir_per_credit,2)}</b></span><span>דקות צפויות <b>${fmt(p.projected_minutes)}</b></span></div>
    <div class="availability-line"><span class="${escape(p.availability)}">● ${{available:'זמין לפי המקור',doubtful:'בספק',unknown:'זמינות לא מאומתת'}[p.availability] || 'לא ידוע'}</span>${confidence(p.confidence)}</div>
    ${p.warnings.length ? `<div class="warning">${p.warnings.map(escape).join(' · ')}</div>` : ''}
    <details><summary>הנתונים מאחורי התחזית</summary><div>PIR אחרון: ${fmt(p.recent_pir)} · ${p.recent_games} הופעות. מול היריבה: ${p.opponent_games} משחקים, ${p.comparable_games} עם בסיס השוואה.</div><div>מחיר שדווח: ${fmt(p.reported_credits)} · ${escape(date(p.price_as_of))} · ${escape(p.price_source || 'אין מקור')}</div><div>זמינות: ${escape(date(p.availability_as_of))} · ${escape(p.availability_source || 'אין מקור')}</div></details>
    </article>`).join('') : '<p class="no-results">אין מועמדים התואמים למסננים. ייתכן שחסרים נתונים, מחירים או משחקים עתידיים.</p>';
  const injured = state.data.excluded.filter(p => p.reason === 'out');
  const inactive = state.data.excluded.filter(p => p.reason === 'inactive_roster');
  $('excluded-note').textContent = [injured.length ? `סטטוס ״בחוץ״ מעודכן: ${injured.map(p => p.name).join(', ')}` : '', inactive.length ? `${inactive.length} שחקנים ללא רישום סגל פעיל אינם ברשימה` : '', 'סטטוס ישן מוצג כלא מאומת.'].filter(Boolean).join(' · ');
}

async function changeMode(mode) {
  state.mode = mode;
  $('round').value = '';
  feedback('');
  await load();
}

$('mode-toggle').addEventListener('click', () => changeMode(state.mode === 'live' ? 'demo' : 'live'));
$('empty-demo').addEventListener('click', () => changeMode('demo'));
['round','window','venue'].forEach(id => $(id).addEventListener('change', load));
['eligible-only','max-price','player-search','ranking'].forEach(id => $(id).addEventListener(id === 'max-price' || id === 'player-search' ? 'input' : 'change', renderPlayers));
$('category-tabs').addEventListener('click', event => {
  const button = event.target.closest('button[data-category]');
  if (!button) return;
  state.category = button.dataset.category;
  state.visible = 12;
  document.querySelectorAll('#category-tabs button').forEach(b => b.classList.toggle('selected', b === button));
  renderDefense(); renderPlayers();
});
$('sort-average').addEventListener('click', () => { state.defenseSort = 'average_pir'; renderDefense(); });
$('sort-effect').addEventListener('click', () => { state.defenseSort = 'matchup_delta_per_30'; renderDefense(); });
$('show-more').addEventListener('click', () => {state.visible = state.visible === 12 ? Infinity : 12; renderPlayers();});

async function fileImport(file, roster) {
  if (!file) return;
  if (file.size > 7_500_000) return feedback('הקובץ גדול מדי. הגודל המרבי הוא 7.5 MB.', true);
  try {
    const contents = await file.text();
    const body = roster ? {csv:contents} : JSON.parse(contents);
    await api(roster ? '/api/roster' : '/api/import', body);
    await changeMode('live');
    feedback('הנתונים נטענו ונבדקו. הניתוח עודכן.');
  } catch (error) { feedback(`הייבוא לא הושלם והמאגר הקודם נשמר: ${error.message}`, true); }
}
$('import-button').addEventListener('click', () => $('import-file').click());
$('roster-button').addEventListener('click', () => $('roster-file').click());
$('import-file').addEventListener('change', event => { fileImport(event.target.files[0], false); event.target.value = ''; });
$('roster-file').addEventListener('change', event => { fileImport(event.target.files[0], true); event.target.value = ''; });

let pollTimer;
async function pollSync() {
  try {
    const job = await api('/api/sync-status');
    if (job.state === 'running') {
      $('sync-button').disabled = true;
      $('market-sync').disabled = true;
      $('sync-status').textContent = job.kind==='market' ? 'קורא מחירים מהמקור המורשה…' : job.total ? `טוען משחקים: ${job.completed} / ${job.total}` : 'בודק לוח משחקים רשמי…';
      pollTimer = setTimeout(pollSync, 1500);
    } else {
      $('sync-button').disabled = state.mode === 'demo';
      if (job.state === 'failed') {
        $('sync-status').textContent = `הסנכרון נכשל; המאגר הקודם נשמר. ${job.error}`;
        feedback(job.kind==='market' ? 'עדכון המחירים לא הושלם. יש לבדוק הרשאה והתאמת נתונים; המאגר הקודם נשמר.' : 'הסנכרון לא הושלם. בדוק גישה למקורות הרשמיים; ייבוא קובץ עדיין זמין.', true);
      } else if (job.state === 'done') {
        $('sync-status').textContent = job.kind==='market' ? 'מחירים עודכנו. מצב פציעות וזמינות דורש מקור נפרד.' : 'הסנכרון הושלם. יש להשלים תפקידי גארדים, מחירים וזמינות דרך CSV.';
        await load();
      }
    }
  } catch (error) { $('sync-status').textContent = `לא ניתן לבדוק את הסנכרון: ${error.message}`; $('sync-button').disabled = false; }
}
$('sync-button').addEventListener('click', async () => {
  $('sync-button').disabled = true;
  clearTimeout(pollTimer);
  try {
    await api('/api/sync', {season:$('season').value.trim()});
    feedback('');
    await pollSync();
  } catch (error) { feedback(error.message, true); $('sync-button').disabled = false; }
});
$('market-sync').addEventListener('click', async()=>{
  $('market-sync').disabled=true;
  clearTimeout(pollTimer);
  try {await api('/api/market-sync',{}); await pollSync();}
  catch(error) {feedback(error.message,true); await load();}
});

load();
pollSync();

function renderScout() {
  const scout=state.data.scouting;
  if(!scout)return;
  const labels={C:'סנטרים',F:'פורוורדים',G:'גארדים'};
  const market=state.data.market;
  const count=state.data.coverage.fresh_prices;
  $('market-summary').innerHTML=state.mode==='demo'?'<span class="market-icon">◈</span><div><strong>מחירים סינתטיים להדגמה בלבד</strong><p>עברו למצב חי לנתוני יורוליג.</p></div>':`<span class="market-icon">◈</span><div><strong>${count?`${count} מחירי שחקנים מעודכנים`:'מחירי הקרדיטים ממתינים לחיבור'}</strong><p>מקור: EuroLeague Fantasy Challenge · ${market?.error?'עדכון המחירים נכשל; מחיר קודם מסומן בנפרד.':market?.connected?'המחירים נבדקים יחד עם עדכון המשחקים.':'רשימת המחירים הרשמית דורשת הרשאה.'}</p></div>`;
  $('top-three').innerHTML=['C','F','G'].map(role=>`<article class="shortlist-column"><header class="position-heading"><span class="role-icon">${role}</span><div><h3>טופ 3 ${labels[role]}</h3><p>${role==='G'?'רכזים וקלעים':'לפי היריבה הקרובה'}</p></div></header>${scout.top_three[role].length ? scout.top_three[role].map((p,i)=>`<article class="shortlist-player ${i===0?'first-choice':''}"><div class="pick-hero"><span class="pick-rank">${i===0?'בחירה מובילה':`מקום ${i+1}`}</span>${portrait(p)}${priceBadge(p)}</div><div class="pick-body"><h4 dir="auto">${escape(displayName(p.name))}</h4><p class="pick-team" dir="auto">${escape(p.team)}</p><div class="fixture-line"><span>מול</span><strong dir="auto">${escape(p.opponent)}</strong><span class="venue-tag">${p.venue==='home'?'בית':'חוץ'}</span></div><p class="fixture-date">${escape(date(p.date))}</p><div class="pick-stats"><div><span>היריבה סופגת בעמדה</span><strong>${fmt(p.opponent_average_pir)} <small>PIR</small></strong></div><div><span>ציון בחירה</span><strong>${fmt(p.scout_score)}</strong></div></div><p class="matchup-explanation"><span class="matchup-pill ${p.matchup_index<1?'negative':''}">${sign((p.matchup_index-1)*100)}%</span> ${p.matchup_index>=1?'יותר':'פחות'} PIR ביחס לליגה · ${p.opponent_games} משחקים</p><div class="pick-footer"><span class="availability-tag ${escape(p.availability)}">${p.availability==='available'?'זמין לפי המקור':p.availability==='doubtful'?'בספק':'זמינות לא מאומתת'}</span>${p.credits!=null?`<span title="${escape(date(p.price_as_of))}">מחיר מעודכן</span>`:''}</div></div></article>`).join(''):'<p class="no-results">אין מספיק משחקים ונתונים לבחירת שלושה מועמדים.</p>'}</article>`).join('');
  $('coach-picks').innerHTML=(scout.coaches||[]).map((c,i)=>`<article class="coach-card"><div class="coach-card-header"><span class="coach-rank">0${i+1}</span>${priceBadge(c)}</div><h3 dir="auto">${escape(displayName(c.name))}</h3><p class="pick-team" dir="auto">${escape(c.team)}</p><div class="fixture-line"><span>מול</span><strong dir="auto">${escape(c.opponent)}</strong><span class="venue-tag">${c.venue==='home'?'בית':'חוץ'}</span></div><p class="fixture-date">${escape(date(c.date))}</p><div class="coach-advantage"><span>מדד יתרון מול היריבה</span><strong class="numeric">${sign(c.matchup_margin)}</strong></div><div class="coach-form"><p>הקבוצה: <b>${c.team_form.wins}/${c.team_form.games}</b> ניצחונות · הפרש <b class="numeric">${sign(c.team_form.average_margin)}</b></p><p>היריבה: <b>${c.opponent_form.wins}/${c.opponent_form.games}</b> ניצחונות · הפרש <b class="numeric">${sign(c.opponent_form.average_margin)}</b></p></div></article>`).join('')||'<p class="no-results">אין מספיק תוצאות או רישום מאמנים רשמי למחזור שנבחר. הרשימה תופיע לאחר עדכון הנתונים.</p>';
  const teams=new Map();
  scout.defenses.forEach(d=>{if(!teams.has(d.team_id))teams.set(d.team_id,{name:d.team,image:d.team_image_url});teams.get(d.team_id)[d.role]=d;});
  $('position-defense-rows').innerHTML=[...teams.values()].sort((a,b)=>{if(state.positionSort){const x=a[state.positionSort]?.average_pir,y=b[state.positionSort]?.average_pir;if(x==null&&y!=null)return 1;if(y==null&&x!=null)return -1;if(x!=null&&y!=null&&x!==y)return state.positionDirection==='desc'?y-x:x-y;}return a.name.localeCompare(b.name);}).map(t=>`<tr><td><span class="defender-name">${imageUrl(t.image)?`<img src="${escape(imageUrl(t.image))}" alt="" width="32" height="32" loading="lazy" referrerpolicy="no-referrer">`:""}<span dir="auto">${escape(t.name)}</span></span></td>${['C','F','G'].map(r=>{const d=t[r];return `<td class="pir-cell ${d&&d.average_pir>=10?'heat-high':d&&d.average_pir>=8?'heat-mid':'heat-low'}">${d?`<b>${fmt(d.average_pir)}</b><small class="confidence"> · ${d.games} משחקים / ${d.appearances} הופעות</small>`:'—'}</td>`;}).join('')}</tr>`).join('')||'<tr><td colspan="4" class="no-results">ממתין לסטטיסטיקות יורוליג.</td></tr>';
  const a=state.data.auto_refresh;
  $('automatic-status').textContent=state.mode==='demo'?'הדגמה סינתטית — אינה מתעדכנת ממשחקים אמיתיים.':a.enabled?`עדכון יורוליג אוטומטי כל ${a.interval_seconds/60} דקות, כל עוד השרת פועל. ${a.last_success?`עדכון מוצלח: ${date(a.last_success)}.`:'ממתין לעדכון ראשון.'} ${a.error?'העדכון האחרון נכשל; הנתונים הקודמים נשמרו.':''}`:'העדכון האוטומטי כבוי בשרת זה.';
}
setInterval(()=>{if(!document.hidden)load();},60000);

document.querySelectorAll('[data-position-sort]').forEach(button=>button.addEventListener('click',()=>{
  const role=button.dataset.positionSort;
  state.positionDirection=state.positionSort===role&&state.positionDirection==='desc'?'asc':'desc';
  state.positionSort=role;
  document.querySelectorAll('[data-position-sort]').forEach(b=>{
    const active=b.dataset.positionSort===role;
    b.closest('th').setAttribute('aria-sort',active?(state.positionDirection==='desc'?'descending':'ascending'):'none');
    b.querySelector('span').textContent=active?(state.positionDirection==='desc'?'↓':'↑'):'↕';
  });
  renderScout();
}));


async function loadSquad() {
  const request=++state.squadRequest;
  if(state.mode==='demo') {
    $('squad-summary').textContent='הסגל האישי מוצג במצב נתונים אמיתיים.';
    $('open-squad').disabled=true;
    return;
  }
  $('open-squad').disabled=false;
  const params=new URLSearchParams({window:$('window').value,venue:$('venue').value});
  if($('round').value)params.set('round',$('round').value);
  if(!$('squad-dialog').open)params.set('summary','1');
  if(state.squadKeepInitialized)params.set('keep',state.squadKeep.join(',')||'none');
  try {
    const data=await api('/api/squad?'+params);
    if(request!==state.squadRequest)return;
    state.squad=data;
    if(!data.available) {
      const message=data.updating?'הסגל נטען במהלך הסנכרון…':data.error?'קריאת הסגל לא הצליחה; ממתין לעדכון הבא.':'הסגל ממתין לחיבור לפנטזי.';
      $('squad-summary').textContent=message;
      $('squad-message').textContent=message;
      $('squad-content').innerHTML='';
      return;
    }
    const s=data.squad;
    if(!state.squadKeepInitialized){state.squadKeep=s.preferred_incoming_ids||[];state.squadKeepInitialized=true;}
    $('squad-summary').textContent=`${s.name} · ${s.previous_round?`סגל סגור ממחזור ${s.previous_round.matchday} → הצעות למחזור ${s.matchday}`:`מחזור ${s.matchday}`} · ${fmt(s.budget)} קרדיטים בתקציב`;
    if($('squad-dialog').open)renderSquad();
  }catch(error) {
    if(request!==state.squadRequest)return;
    $('squad-message').textContent='לא הצלחתי לטעון את הסגל. אפשר לנסות שוב.';
  }
}

function squadRow(p, extra='') {
  return `<div class="squad-player-row">${portrait(p,'squad-portrait')}<div class="squad-player-name"><strong dir="auto">${escape(displayName(p.name))}</strong><span dir="auto">${escape(p.team||'')}</span>${p.opponent?`<small>מול ${escape(p.opponent)}</small>`:''}</div><div class="squad-player-price"><b>${fmt(p.credits)}</b><small>קרדיטים</small>${extra}</div></div>`;
}
function squadRoster(rows) {
  const labels={G:'גארדים',F:'פורוורדים',C:'סנטרים',H:'מאמן'};
  return ['G','F','C','H'].map(r=>`<div class="squad-role"><h4>${labels[r]}</h4>${rows.filter(p=>p.role===r).map(p=>squadRow(p,p.captain?'<span class="captain-tag">קפטן</span>':'')).join('')}</div>`).join('');
}
function renderSquad() {
  const data=state.squad;
  if(!data?.available)return;
  const s=data.squad, plans=data.plans, choices=plans?.alternatives||[];
  state.selectedPlan=Math.min(state.selectedPlan,Math.max(0,choices.length-1));
  const raw=s.previous_round?.players||s.players, current=plans?.current_players||raw;
  const incoming=s.draft_transfers?.in||[], outgoing=s.draft_transfers?.out||[];
  const draft=incoming.length||outgoing.length?`<details class="squad-draft" open><summary>התכנון שכבר שינית למחזור ${s.matchday}</summary><div class="squad-draft-columns"><div><h4>נכנסים בתכנון הנוכחי</h4>${incoming.map(p=>`<label class="draft-keep"><input type="checkbox" data-squad-keep="${escape(p.fantasy_player_id)}" ${state.squadKeep.includes(p.fantasy_player_id)?'checked':''}><span><strong dir="auto">${escape(displayName(p.name))}</strong><small>${fmt(p.credits)} קרדיטים · לשמור בבחירה</small></span></label>`).join('')}</div><div><h4>יוצאים מהסגל הסגור</h4>${outgoing.map(p=>`<p dir="auto">${escape(displayName(p.name))}</p>`).join('')}</div></div><p class="squad-draft-note">בסיס ההצעות הוא הסגל הסגור של המחזור הקודם. אפשר לסמן בחירות שרוצים לשמור בחלופות.</p></details>`:'';
  $('squad-message').textContent=`עודכן ${date(s.observed_at)}${data.error?' · קריאת הסגל האחרונה נכשלה; מוצג העדכון האחרון.':''}${data.updating?' · סנכרון נוסף מתבצע כעת.':''}`;
  $('squad-content').innerHTML=`<div class="squad-wallet"><article><span>שווי בתכנון הנוכחי</span><strong>${fmt(s.roster_value)}</strong></article><article><span>קרדיטים פנויים</span><strong>${fmt(s.free_credits)}</strong></article><article><span>תקציב כולל</span><strong>${fmt(s.budget)}</strong></article><article><span>חילופים בתכנון הנוכחי</span><strong class="numeric">${s.transfers_used}${s.transfers_limit==null?' / ללא מגבלה':` / ${s.transfers_limit}`}</strong></article></div><nav class="squad-dialog-nav" aria-label="ניווט בחלונית הסגל"><button type="button" data-squad-jump="squad-options">אפשרויות לשיפור ↓</button><button type="button" data-squad-jump="squad-current">הסגל הסגור ↓</button></nav>${draft}<div class="squad-layout"><section id="squad-current" class="squad-current"><h3>${s.previous_round?`הסגל הסגור · מחזור ${s.previous_round.matchday}`:`הסגל הנוכחי · מחזור ${s.matchday}`}</h3><p class="squad-roster-caption">מחירי היום משמשים להשוואת ההעברות למחזור הבא.</p>${squadRoster(current)}</section><section id="squad-options" class="squad-options"><h3>הצעות למחזור ${s.matchday} מהסגל הסגור</h3>${plans?.available?`${choices.length?`<div class="squad-choice-tabs">${choices.map((p,i)=>`<button type="button" data-squad-plan="${i}" class="${i===state.selectedPlan?'selected':''}">${escape(p.title)}</button>`).join('')}</div><div id="squad-plan-detail"></div>`:`<p class="squad-empty">${s.transfers_remaining===0&&!plans.can_replan?'לא נותרו חילופים נוספים למחזור זה.':'לא נמצאה חלופת חילופים שמשפרת את הציון ועומדת בתקציב ובמגבלות.'}</p><div id="squad-plan-detail"></div>`}${plans.missing_forecasts?.length?`<p class="squad-note">אין מספיק נתונים לחיזוי עבור ${plans.missing_forecasts.map(p=>escape(displayName(p))).join(', ')}. לבחירות האלה אין הערכה במדד; ההשוואה מחושבת רק לרכיבים עם נתונים.</p>`:''}`:`<p class="squad-empty">${escape(plans?.reason||'מחשב אפשרויות…')}</p>`}<details class="squad-method"><summary>איך ההצעות מחושבות?</summary><p>החלופות שומרות על התקציב, 4 גארדים, 4 פורוורדים, 2 סנטרים ומאמן, מגבלת שחקנים מאותו מועדון ומספר החילופים שהמשחק מתיר. ההשוואה מתבססת על הסגל הסגור של המחזור הקודם; התכנון שכבר ערכת מוצג בנפרד.</p><p>המדד משלב PIR לפי היריבה עם ניקוד מאמן משוער. בחיזוי מלא: חמישייה ושחקן שישי מקבלים משקל מלא, קפטן כפול וספסל חצי. בונוס ניצחון לשחקנים אינו כלול. זהו מדד להשוואת חלופות, לא תחזית ניקוד פנטזי מאומתת או הבטחה להרכב מיטבי.</p></details></section></div>`;
  if(plans?.available)renderSquadPlan();
  document.querySelectorAll('[data-squad-keep]').forEach(input=>input.addEventListener('change',()=>{const id=input.dataset.squadKeep;state.squadKeep=input.checked?[...new Set([...state.squadKeep,id])]:state.squadKeep.filter(p=>p!==id);$('squad-message').textContent='מעדכן את החלופות לפי הבחירות שסימנת…';loadSquad();}));
  document.querySelectorAll('[data-squad-jump]').forEach(button=>button.addEventListener('click',()=>$(button.dataset.squadJump).scrollIntoView({block:'start'})));
  document.querySelectorAll('[data-squad-plan]').forEach(button=>button.addEventListener('click',()=>{state.selectedPlan=Number(button.dataset.squadPlan);renderSquad();}));
}
function renderSquadPlan() {
  const plans=state.squad.plans, choice=plans.alternatives[state.selectedPlan], container=$('squad-plan-detail');
  if(!container)return;
  const allocation=choice?.lineup||plans.current_lineup, rows=choice?.players||plans.current_players;
  let html='';
  if(choice) {
    html=`<div class="squad-comparison"><div><span>מדד הסגל הסגור</span><strong>${fmt(plans.current_model_score)}</strong></div><span class="comparison-arrow">←</span><div><span>אחרי השינויים</span><strong>${fmt(choice.model_score)}</strong></div><span class="matchup-pill ${choice.improvement<0?'negative':''}">${sign(choice.improvement)}</span></div><div class="squad-plan-budget"><span>${choice.transfer_count} שינויים מהסגל הסגור · ${choice.net_transfer_count} חילופים בסך הכול במחזור</span><strong>${fmt(choice.free_credits)} קרדיטים יישארו</strong></div><h4>העברות לביצוע במשחק</h4>${choice.transfers.map(t=>`<div class="squad-transfer"><div class="transfer-out"><span>להוציא</span><strong dir="auto">${escape(displayName(t.out.name))}</strong><small>${fmt(t.out.credits)} קרדיטים</small></div><span class="transfer-arrow">←</span><div class="transfer-in"><span>להכניס</span><strong dir="auto">${escape(displayName(t.in.name))}</strong><small>${fmt(t.in.credits)} קרדיטים · מול ${escape(t.in.opponent||'—')}</small></div></div>`).join('')}<details class="planned-roster"><summary>הסגל המלא אחרי השינויים</summary>${squadRoster(choice.players)}</details>`;
  }
  if(allocation) {
    const index=Object.fromEntries(rows.map(p=>[p.fantasy_player_id,p]));
    const names=ids=>ids.map(id=>escape(displayName(index[id]?.name))).join(' · ');
    html+=`<div class="squad-lineup"><h4>${choice?'סידור מוצע לחלופה':'סידור מוצע לסגל הסגור לקראת המחזור הבא'}</h4><p><b>חמישייה (<span class="numeric">${allocation.formation.join('–')}</span>):</b> ${names(allocation.starters)}</p><p><b>קפטן:</b> ${names([allocation.captain])}</p><p><b>שחקן שישי:</b> ${names([allocation.sixth])}</p><p><b>ספסל:</b> ${names(allocation.bench)}</p><p><b>מאמן:</b> ${names([allocation.coach])}</p></div>`;
  }
  container.innerHTML=html;
}
$('open-squad').addEventListener('click',()=>{
  $('squad-dialog').showModal();document.body.classList.add('modal-open');
  $('squad-message').textContent='טוען את הסגל ומחשב אפשרויות…';
  loadSquad();
});
$('close-squad').addEventListener('click',()=>$('squad-dialog').close());
$('squad-dialog').addEventListener('close',()=>{document.body.classList.remove('modal-open');++state.squadRequest;});
