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

await page.goto(url + '?case=segmented-date', {waitUntil: 'networkidle'});
const month = page.locator('#d1 [data-part="month"]');
await month.click();
const selectedMonth = await month.evaluate(el => [el.selectionStart, el.selectionEnd, el.value.length]);
if (selectedMonth[0] !== 0 || selectedMonth[1] !== selectedMonth[2]) {
  throw new Error('Clicking a date segment should select its whole value');
}
await month.pressSequentially('10');
if (await page.evaluate(() => document.activeElement?.dataset.part) !== 'day') {
  throw new Error('Completing the month should advance to the day');
}
await page.keyboard.type('16');
if (await page.evaluate(() => document.activeElement?.dataset.part) !== 'year') {
  throw new Error('Completing the day should advance to the year');
}
await page.keyboard.type('2000');
await page.keyboard.press('Enter');
await page.waitForTimeout(350);
const committedStart = await page.evaluate(() => location.hash.slice(1).split('|')[3]);
if (committedStart !== '2000-10-16') {
  throw new Error('Enter should commit the typed date');
}

console.log('theme returns interaction tests passed');
