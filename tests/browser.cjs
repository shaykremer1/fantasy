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
    await page.goto(base);
    await page.waitForFunction(() => document.getElementById('updated').textContent.includes('הניתוח חושב'));
    assert.equal(await page.locator('#stat-players').innerText(), '0');
    assert(await page.locator('#empty').isVisible());
    await page.locator('#mode-toggle').click();
    await page.waitForFunction(() => document.getElementById('stat-players').textContent === '30');
    assert(await page.locator('#demo-banner').isVisible());
    assert.equal(await page.locator('.shortlist-column').count(),3);
    assert.equal(await page.locator('.shortlist-player').count(),9);
    assert.equal(await page.locator('#position-defense-rows tr').count(),6);
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
