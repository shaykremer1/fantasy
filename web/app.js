const $ = id => document.getElementById(id);
const state = {mode: 'live', category: 'C', defenseSort: 'matchup_delta_per_30', data: null, request: 0, visible:12, positionSort:null, positionDirection:'desc'};
const fmt = (value, digits = 1) => value == null ? '—' : Number(value).toLocaleString('he-IL', {maximumFractionDigits: digits});
const sign = (value,digits=1) => value == null ? '—' : `${value > 0 ? '+' : ''}${fmt(value,digits)}`;
const date = value => value ? new Date(value).toLocaleString('he-IL', {timeZone: 'Asia/Jerusalem', dateStyle: 'short', timeStyle: 'short'}) : 'אין עדכון';
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const numeric = value => `<span class="numeric">${fmt(value)}</span>`;
const confidence = value => `<span class="confidence ${escape(value)}"><i></i><i></i><i></i> ${{low:'קטן',medium:'בינוני',higher:'גדול יותר'}[value]}</span>`;

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
    $('market-connection').textContent = market.last_import ? `עודכנו ${market.last_import.matched} מחירים; ${market.last_import.unmatched} שחקנים לא הותאמו.` : market.credential_present ? 'קיימת הרשאה לבדיקה; החיבור החי עדיין לא אומת.' : 'נדרשת הרשאה לקריאת מחירים. אפשר להמשיך בייבוא CSV.';
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
    <div class="player-header"><span class="player-avatar">${escape(p.name.trim().slice(0,2))}</span><div><h3>${escape(p.name)}</h3><small>${escape(p.team)}</small></div><span class="position-chip">${escape(p.position)}</span></div>
    <div class="opponent-line">מול <b>${escape(p.opponent)}</b> · ${p.venue === 'home' ? 'בית' : 'חוץ'} · ${escape(date(p.date))}</div>
    <div class="prediction"><div><span>תחזית PIR</span><strong>${fmt(p.projected_pir)}</strong></div><div class="boost"><span>יתרון היריבה</span><strong class="${p.matchup_delta < 0 ? 'negative' : ''}">${sign(p.matchup_delta)}</strong></div></div>
    <div class="player-details"><span>קרדיטים <b>${fmt(p.credits)}</b></span><span>PIR לקרדיט <b>${fmt(p.pir_per_credit,2)}</b></span><span>דקות צפויות <b>${fmt(p.projected_minutes)}</b></span></div>
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
  const labels={C:'טופ 3 סנטרים',F:'טופ 3 פורוורדים',G:'טופ 3 גארדים (רכזים וקלעים)'};
  $('top-three').innerHTML=['C','F','G'].map(role=>`<article class="shortlist-column"><h3>${labels[role]}</h3>${scout.top_three[role].length ? scout.top_three[role].map((p,i)=>`<div class="shortlist-player"><strong>${i+1}. ${escape(p.name)}</strong><p>${escape(p.team)} מול ${escape(p.opponent)} · ${escape(date(p.date))}</p><p>היריבה מאפשרת <b>${fmt(p.opponent_average_pir)} PIR</b> לשחקן בעמדה · ${p.opponent_games} משחקים</p><p>התאמת יריבה: <b class="numeric">${fmt((p.matchup_index-1)*100)}%</b> ביחס לליגה · ציון בחירה <b>${fmt(p.scout_score)}</b></p><small>${p.availability==='available'?'זמין לפי המקור':p.availability==='doubtful'?'בספק':'זמינות לא מאומתת'}${p.credits==null?' · מחיר לא ידוע':` · ${fmt(p.credits)} קרדיטים`}</small></div>`).join(''):'<p class="no-results">אין מספיק משחקים ונתונים לבחירת שלושה מועמדים.</p>'}</article>`).join('');
  $('coach-picks').innerHTML=(scout.coaches||[]).map((c,i)=>`<article class="coach-card"><h3>${i+1}. ${escape(c.name)}</h3><p>${escape(c.team)} מול ${escape(c.opponent)} · ${c.venue==='home'?'בית':'חוץ'}</p><p>${escape(date(c.date))}</p><p>מדד יתרון מול היריבה: <b class="numeric">${fmt(c.matchup_margin)}</b></p><p>הקבוצה: ${c.team_form.wins} ניצחונות ב־${c.team_form.games} משחקים · הפרש ממוצע <b class="numeric">${fmt(c.team_form.average_margin)}</b></p><p>היריבה: ${c.opponent_form.wins} ניצחונות ב־${c.opponent_form.games} משחקים · הפרש ממוצע <b class="numeric">${fmt(c.opponent_form.average_margin)}</b></p></article>`).join('')||'<p class="no-results">אין מספיק תוצאות או רישום מאמנים רשמי למחזור שנבחר. הרשימה תופיע לאחר עדכון הנתונים.</p>';
  const teams=new Map();
  scout.defenses.forEach(d=>{if(!teams.has(d.team_id))teams.set(d.team_id,{name:d.team});teams.get(d.team_id)[d.role]=d;});
  $('position-defense-rows').innerHTML=[...teams.values()].sort((a,b)=>{if(state.positionSort){const x=a[state.positionSort]?.average_pir,y=b[state.positionSort]?.average_pir;if(x==null&&y!=null)return 1;if(y==null&&x!=null)return -1;if(x!=null&&y!=null&&x!==y)return state.positionDirection==='desc'?y-x:x-y;}return a.name.localeCompare(b.name);}).map(t=>`<tr><td>${escape(t.name)}</td>${['C','F','G'].map(r=>{const d=t[r];return `<td>${d?`<b>${fmt(d.average_pir)}</b><small class="confidence"> · ${d.games} משחקים / ${d.appearances} הופעות</small>`:'—'}</td>`;}).join('')}</tr>`).join('')||'<tr><td colspan="4" class="no-results">ממתין לסטטיסטיקות יורוליג.</td></tr>';
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
