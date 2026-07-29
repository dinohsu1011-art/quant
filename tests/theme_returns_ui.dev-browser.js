const page = await browser.getPage('theme-returns-ui-test');
const url = 'http://127.0.0.1:8765/market-lab-themes.html';

await page.goto(url + '?case=enter', {waitUntil: 'networkidle'});
await page.locator('#q').fill('MU');
await page.locator('#q').press('Enter');
await page.waitForTimeout(350);
let selected = await page.evaluate(() => location.hash.slice(1).split('|')[0].split(','));
if (!selected.includes('MU') || await page.locator('#tbl tbody tr[data-id="MU"]').count() !== 1) {
  throw new Error('Enter should select the exact ticker in the search box');
}

await page.goto(url + '?case=foreign-ticker', {waitUntil: 'networkidle'});
await page.locator('#q').fill('005930.KS');
await page.locator('#q').press('Enter');
await page.waitForTimeout(350);
selected = await page.evaluate(() => location.hash.slice(1).split('|')[0].split(','));
if (!selected.includes('kr005930')) {
  throw new Error('Enter should resolve a foreign exchange ticker to its chart series');
}

await page.goto(url + '?case=table-clicks', {waitUntil: 'networkidle'});
for (const ticker of ['MU', 'NVDA']) {
  await page.locator('#q').fill(ticker);
  await page.locator('#q').press('Enter');
  await page.waitForTimeout(100);
}
await page.locator('#tbl tbody tr[data-id="MU"]').click();
await page.waitForTimeout(350);
if (await page.locator('#tbl tbody tr[data-id="NVDA"].dim').count() !== 1) {
  throw new Error('Single click should continue to focus the selected ticker');
}
await page.locator('#tbl tbody tr[data-id="MU"]').dblclick();
await page.waitForTimeout(350);
selected = await page.evaluate(() => location.hash.slice(1).split('|')[0].split(','));
if (selected.includes('MU') || !selected.includes('NVDA')) {
  throw new Error('Double click should remove only the double-clicked ticker');
}

console.log('theme returns interaction tests passed');
