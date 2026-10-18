// Uses the cloud image's existing Playwright + Chromium. No application dependency.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

(async () => {
  let testServer, folder;
  let base = process.env.FANTASY_TEST_URL;
  if (!base) {
    folder = fs.mkdtempSync(path.join(os.tmpdir(), 'fantasy-browser-'));
    testServer = spawn('python', ['-m', 'app.server', '--port', '0', '--no-auto-sync', '--data', path.join(folder,'live.json')], {cwd:path.resolve(__dirname,'..'), env:{...process.env,FANTASY_ACCESS_TOKEN:''},stdio:['ignore','pipe','pipe']});
    base = await new Promise((resolve,reject) => {
      const timer = setTimeout(() => {testServer.kill(); reject(new Error('Isolated browser server failed to start'));}, 10000);
      testServer.once('error', error => {clearTimeout(timer); reject(error);});
      testServer.stdout.on('data', bytes => {
        const match = bytes.toString().match(/listening on port (\d+)/);
        if (match) {clearTimeout(timer); resolve(`http://127.0.0.1:${match[1]}`);}
      });
    });
  }
  const browser = await chromium.launch({executablePath:'/usr/bin/chromium', headless:true, args:['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const rosterRoles=['G','G','G','G','F','F','F','F','C','C','H'];
    const squadPlayers=rosterRoles.map((role,i)=>({fantasy_player_id:String(i+1),player_id:`P${i+1}`,name:`TEST, PLAYER ${i+1}`,role,team:'Synthetic club',credits:10}));
    const lineup={starters:['1','2','5','6','9'],captain:'1',sixth:'7',bench:['3','4','8','10'],coach:'11',formation:[2,2,1]};
    const alternatives=[0,1,2].map(i=>{
      const incoming={...squadPlayers[0],fantasy_player_id:String(21+i),name:`UPGRADE, OPTION ${i+1}`,credits:11,opponent:'Synthetic opponent'};
      return {title:['הציון הגבוה ביותר שנמצא','שיפור ממוקד','שיפור בלי להגדיל הוצאות'][i],players:[incoming,...squadPlayers.slice(1)],transfers:[{out:squadPlayers[0],in:incoming}],transfer_count:1,net_transfer_count:1,model_score:140+i,improvement:20+i,roster_value:111,free_credits:1.5,lineup:{...lineup,starters:[String(21+i),'2','5','6','9'],captain:String(21+i)}};
    });
    let lastSquadKeep=null;
    await page.route('**/api/squad?**',route=>{lastSquadKeep=new URL(route.request().url()).searchParams.get('keep');return route.fulfill({json:{available:true,squad:{name:'Synthetic test squad',players:[{...squadPlayers[0],fantasy_player_id:'31',name:'PLANNED, CURRENT'},...squadPlayers.slice(1)],previous_round:{matchday:10,players:squadPlayers,complete:true},draft_transfers:{in:[{...squadPlayers[0],fantasy_player_id:'31',name:'PLANNED, CURRENT'}],out:[squadPlayers[0]]},preferred_incoming_ids:[],budget:112.5,roster_value:110,free_credits:2.5,matchday:11,observed_at:new Date().toISOString(),transfers_used:0,transfers_limit:4},plans:{available:true,alternatives,current_players:squadPlayers,current_model_score:120,current_lineup:lineup,missing_forecasts:[]}}});});
    // A failed first request (for example while Render wakes) must recover unaided.
    let dashboardAttempts=0;
    await page.route('**/api/dashboard?**',route=>{
      dashboardAttempts++;
      return dashboardAttempts===1 ? route.fulfill({status:503,contentType:'text/html',body:'Starting service'}) : route.continue();
    });
    await page.goto(base);
    await page.waitForFunction(()=>document.getElementById('feedback').textContent.includes('מנסה שוב'));

    await page.waitForFunction(() => document.getElementById('updated').textContent.includes('הניתוח חושב'));
    assert(dashboardAttempts>=2);
    assert(await page.locator('#feedback').isHidden());
    await page.unroute('**/api/dashboard?**');
    assert.equal(await page.locator('#stat-players').innerText(), '0');
    assert(await page.locator('#empty').isVisible());
    await page.waitForFunction(()=>document.getElementById('squad-summary').textContent.includes('Synthetic test squad'));
    await page.locator('#open-squad').click();
    await page.waitForFunction(()=>document.querySelectorAll('.squad-choice-tabs button').length===3);
    assert(await page.locator('#squad-dialog').isVisible());
    assert.equal(await page.locator('.squad-current .squad-player-row').count(),11);
    assert((await page.locator('.squad-current h3').innerText()).includes('מחזור 10'));
    assert(!(await page.locator('.squad-current').innerText()).includes('CURRENT PLANNED'));
    assert((await page.locator('.squad-draft').innerText()).includes('CURRENT PLANNED'));
    assert(!(await page.locator('[data-squad-keep="31"]').isChecked()));
    await page.locator('[data-squad-keep="31"]').check();
    await page.waitForFunction(()=>!document.getElementById('squad-message').textContent.includes('מעדכן'));
    assert.equal(lastSquadKeep,'31');
    await page.locator('[data-squad-keep="31"]').uncheck();
    await page.waitForFunction(()=>!document.getElementById('squad-message').textContent.includes('מעדכן'));
    assert.equal(lastSquadKeep,'none');
    assert.equal(await page.locator('.squad-options > #squad-plan-detail > .squad-transfer').count(),1);
    assert((await page.locator('#squad-plan-detail').innerText()).includes('מה לשנות בתכנון הנוכחי'));
    assert((await page.locator('.squad-wallet').innerText()).includes('112.5'));
    assert((await page.locator('#squad-plan-detail').innerText()).includes('OPTION 1'));
    await page.locator('[data-squad-plan="1"]').click();
    assert((await page.locator('#squad-plan-detail').innerText()).includes('OPTION 2'));
    await page.setViewportSize({width:390,height:844});
    const dialogSize=await page.locator('#squad-dialog').evaluate(d=>[d.scrollWidth,d.clientWidth]);
    assert(dialogSize[0]<=dialogSize[1]+1,`Squad modal overflow: ${dialogSize}`);
    await page.locator('#squad-dialog').screenshot({path:'/tmp/fantasy-squad-mobile.png'});
    await page.keyboard.press('Escape');
    assert(await page.locator('#squad-dialog').isHidden());
    await page.setViewportSize({width:1440,height:1000});

    await page.locator('#mode-toggle').click();
    await page.waitForFunction(() => document.getElementById('stat-players').textContent === '30');
    assert(await page.locator('#demo-banner').isVisible());
    assert(await page.locator('#open-squad').isDisabled());
    assert.equal(await page.locator('.shortlist-column').count(),3);
    assert.equal(await page.locator('.shortlist-player').count(),9);
    assert.equal(await page.locator('#coach-picks .coach-card').count(),3);
    assert((await page.locator('#coach-picks').innerText()).includes('מול'));
    assert((await page.locator('#coach-picks').innerText()).includes('היריבה:'));
    assert.equal(await page.locator('#position-defense-rows tr').count(),6);
    assert.equal(await page.locator('#top-three img[data-portrait]').count(),9);
    assert.equal(await page.locator('#top-three .credit-badge:not(.missing)').count(),9);
    // Exercise a portrait response and a failed portrait without relying on remote CDN access.
    await page.route('https://media-cdn.cortextech.io/test-portrait.png',route=>route.fulfill({status:200,contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="112"><rect width="100" height="112" fill="#406655"/></svg>'}));
    await page.route('https://media-cdn.cortextech.io/broken-portrait.png',route=>route.fulfill({status:404,body:''}));
    await page.route('**/api/dashboard?**',async route=>{
      const response=await route.fetch();
      const data=await response.json();
      if(data.mode==='demo') {
        data.scouting.top_three.C[0].image_url='https://media-cdn.cortextech.io/test-portrait.png';
        data.scouting.top_three.C[1].image_url='https://media-cdn.cortextech.io/broken-portrait.png';
        data.scouting.top_three.C[2].credits=null;
        data.scouting.top_three.C[2].reported_credits=8.5;
      }
      await route.fulfill({response,json:data});
    });
    await page.locator('#window').selectOption('5');
    await page.waitForFunction(()=>document.querySelector('#top-three .shortlist-player img')?.src.includes('test-portrait.png'));
    await page.locator('#shortlist').scrollIntoViewIfNeeded();
    await page.waitForFunction(()=>document.querySelector('#top-three .shortlist-player img')?.naturalWidth>0);
    await page.waitForFunction(()=>document.querySelectorAll('#top-three .shortlist-player img')[1]?.src.endsWith('/player-placeholder.svg'));
    assert.equal(await page.locator('#top-three .credit-badge.stale').count(),1);
    assert((await page.locator('#top-three .credit-badge.stale').innerText()).includes('מחיר קודם'));
    await page.unroute('**/api/dashboard?**');
    await page.locator('#window').selectOption('10');
    await page.waitForFunction(()=>document.querySelector('#top-three .credit-badge.stale')===null);

    for (const [role,col] of [['C',1],['F',2],['G',3]]) {
      const button=page.locator(`[data-position-sort="${role}"]`);
      for (const descending of [true,false]) {
        await button.click();
        const values=await page.locator('#position-defense-rows tr').evaluateAll((rows,col)=>rows.map(r=>Number(r.cells[col].querySelector('b').textContent)),col);
        assert.deepEqual(values,[...values].sort((a,b)=>descending?b-a:a-b));
        assert.equal(await button.locator('..').getAttribute('aria-sort'),descending?'descending':'ascending');
      }
    }

    await page.locator('#advanced > summary').click();
    await page.waitForFunction(()=>document.getElementById('validation-message').textContent.includes('בדיקה סינתטית'));
    assert(await page.locator('#validation-metrics').isVisible());
    assert(Number(await page.locator('#evaluation-n').innerText())>0);
    assert(await page.locator('#market-sync').isDisabled());
    assert.equal(await page.locator('#defense-rows tr').count(), 6);
    assert.equal(await page.locator('.player-card').count(), 5);
    await page.locator('[data-category="PG"]').click();
    assert.equal(await page.locator('.player-card').count(), 6);
    await page.locator('#eligible-only').check();
    assert.equal(await page.locator('.player-card').count(), 6);
    await page.locator('[data-category="W"]').click();
    assert.equal(await page.locator('.player-card').count(), 12);
    await page.locator('#show-more').click();
    assert.equal(await page.locator('.player-card').count(), 16);
    await page.locator('#player-search').fill('no-player-matches-this');
    assert.equal(await page.locator('.player-card').count(), 0);
    await page.locator('#player-search').fill('');
    await page.locator('#max-price').fill('1');
    assert.equal(await page.locator('.player-card').count(), 0);
    await page.locator('#max-price').fill('');
    await page.locator('#eligible-only').uncheck();
    await page.locator('[data-category="C"]').click();
    await page.locator('#window').selectOption('5');
    await page.waitForFunction(() => Array.from(document.querySelectorAll('#defense-rows tr')).every(r => r.cells[4].textContent.trim().startsWith('5')));
    await page.locator('#window').selectOption('10');
    await page.waitForFunction(() => Array.from(document.querySelectorAll('#defense-rows tr')).every(r => r.cells[4].textContent.trim().startsWith('10')));
    await page.screenshot({path:'/tmp/fantasy-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'/tmp/fantasy-mobile.png',fullPage:true});
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    assert(widths[0] <= widths[1], `Mobile overflow: ${widths}`);
    await page.locator('#mode-toggle').click();
    await page.waitForFunction(() => document.getElementById('stat-players').textContent === '0');
    assert(!(await page.locator('#demo-banner').isVisible()));
    assert.deepEqual(errors, []);
    if (process.env.FANTASY_LIVE_TEST_URL) {
      await page.goto(process.env.FANTASY_LIVE_TEST_URL);
      await page.waitForFunction(() => document.getElementById('updated').textContent.includes('הניתוח חושב'));
      const live = await (await page.request.get(`${process.env.FANTASY_LIVE_TEST_URL}/api/dashboard`)).json();
      assert(live.coverage.games_with_stats > 0);
      assert.equal(await page.locator('#stat-games').innerText(), String(live.coverage.games_with_stats));
      assert(await page.locator('#demo-banner').isHidden());
      const evaluation = await (await page.request.get(`${process.env.FANTASY_LIVE_TEST_URL}/api/backtest`)).json();
      if (evaluation.available && evaluation.summary.n>0) {
        await page.locator('#advanced > summary').click();
        const n = evaluation.segments.holdout.n || evaluation.summary.n;
        await page.waitForFunction(n=>Number(document.getElementById('evaluation-n').textContent.replace(/,/g,''))===n,n);
        assert(await page.locator('#validation-metrics').isVisible());
        assert((await page.locator('#validation-message').innerText()).includes(evaluation.season));
      }
      await page.setViewportSize({width:1440,height:1000});
      await page.screenshot({path:'/tmp/fantasy-live.png',fullPage:true});
    }
    console.log('Browser checks passed: empty live state, separate demo, position filters, eligibility, search, budget, game window, and mobile layout.');
  } finally {
    await browser.close();
    if (testServer) {
      testServer.kill();
      await new Promise(resolve => testServer.once('exit',resolve));
    }
    if (folder) fs.rmSync(folder,{recursive:true,force:true});
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
