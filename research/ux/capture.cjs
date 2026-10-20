// Requires Node, Playwright and Microsoft Edge. Optional PLAYWRIGHT_MODULE selects a module path.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const path=require('path');const fs=require('fs');const {pathToFileURL}=require('url');
(async()=>{
const browser=await chromium.launch({headless:true,channel:'msedge'});
const page=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:2});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const base=pathToFileURL(path.join(__dirname,'wireframes.html')).href;
const checks=[];
for(const width of [360,390,430]){await page.setViewportSize({width,height:844});for(const screen of ['feed','detail','chat']){await page.goto(base+'?screen='+screen);const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);if(overflow)throw Error('Overflow '+width+' '+screen);checks.push(`${width}px ${screen}: no horizontal overflow`);}}
await page.setViewportSize({width:390,height:844});await page.goto(base);
await page.getByRole('button',{name:'Открыть разбор'}).first().click();
if(!await page.getByText('Почему это касается вас',{exact:true}).isVisible())throw Error('Detail missing');
await page.getByRole('button',{name:'Что проверить в первую очередь?',exact:true}).click();await page.waitForTimeout(500);
if(await page.locator('.message').count()!==2)throw Error('Chat missing');
await page.getByRole('button',{name:'Развернуть аналитику',exact:true}).click();
if(!await page.getByText('Почему это касается вас',{exact:true}).isVisible())throw Error('Expand failed');
await page.getByRole('button',{name:'Свернуть аналитику',exact:true}).click();
if(await page.locator('.message').count()!==2)throw Error('Messages lost');
await page.getByRole('button',{name:'Отправить вопрос'}).click();if(await page.locator('.message').count()!==2)throw Error('Empty sent');
await page.getByRole('button',{name:'Проверить состояние ошибки'}).click();await page.locator('#input').fill('Какие данные нужны?');await page.getByRole('button',{name:'Отправить вопрос'}).click();await page.waitForTimeout(500);
await page.getByRole('button',{name:'Повторить',exact:true}).click();await page.waitForTimeout(500);if(await page.locator('.message.user').count()!==2)throw Error('Retry duplicate');
checks.push('Feed → detail → chat; expand/collapse preserves messages; empty input ignored; error/retry without duplicate: passed');
await page.goto(base+'?screen=feed');
if(await page.locator('article.card').count()!==6)throw Error('Expected 6 news cards');
for(const id of ['steel','credit','logistics','procurement','energy','exhibition']){
 await page.goto(base+'?screen=feed');
 await page.locator(`[data-event="${id}"] button`).click();
 if(!await page.locator('h1').textContent())throw Error('Missing event title');
 if(['credit','procurement'].includes(id)&&!await page.getByText('Позиция Альфа-Банка · вымышленный пример',{exact:true}).isVisible())throw Error('Bank demo missing');
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Demo overflow '+id);
 await page.getByRole('button',{name:'Что проверить в первую очередь?',exact:true}).click();await page.waitForTimeout(500);
 if(await page.locator('.message').count()!==2)throw Error('Demo chat missing '+id);
}
await page.goto(base+'?screen=detail&event=credit');
await page.getByRole('button',{name:'Что проверить в первую очередь?',exact:true}).click();await page.waitForTimeout(500);
await page.evaluate(()=>go('detail','energy'));if(await page.locator('.message').count())throw Error('History leaked');
await page.evaluate(()=>go('chat','credit'));if(await page.locator('.message').count()!==2)throw Error('History not restored');
checks.push('6 news items; all importance levels; 2 fictional bank reviews; event-specific details/chat; isolated histories: passed');
await page.goto(base+'?screen=detail');await page.locator('.ai .ref').click();if(await page.evaluate(()=>location.hash)!=='#source-1')throw Error('Citation anchor failed');checks.push('Citation anchor and external source URL: passed');
for(const [i,screen] of ['feed','detail','chat'].entries()){await page.goto(base+'?screen='+screen);if(screen==='detail')await page.evaluate(()=>{document.body.classList.add('capture');document.querySelector('.app').append(document.getElementById('composer'))});await page.screenshot({path:path.join(__dirname,`0${i+1}-${screen}.png`),fullPage:screen==='detail'});}
await page.goto(base+'?screen=detail&event=credit');await page.evaluate(()=>{document.body.classList.add('capture');document.querySelector('.app').append(document.getElementById('composer'))});await page.screenshot({path:path.join(__dirname,'04-bank-demo.png'),fullPage:true});
await page.goto(base+'?screen=feed');await page.screenshot({path:path.join(__dirname,'05-feed-all.png'),fullPage:true});
if(errors.length)throw Error(errors.join('\n'));checks.push('Browser JS errors: 0');
fs.writeFileSync(path.join(__dirname,'qa-results.json'),JSON.stringify({checked_at:new Date().toISOString(),browser:'Microsoft Edge / Playwright',checks},null,2));
await browser.close();console.log(checks.join('\n'));
})().catch(e=>{console.error(e);process.exit(1)});
