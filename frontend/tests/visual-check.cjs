const {chromium,expect}=require('@playwright/test');
(async()=>{
 const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:3000/');
 await expect(page.locator('.stat-card strong').first()).toHaveText(/\d+/);
 await expect(page.locator('.recharts-sector').first()).toBeVisible();
 await page.screenshot({path:'../storage/browser-overview.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await expect(page.locator('.recharts-sector').first()).toBeVisible();await page.screenshot({path:'../storage/browser-mobile.png',fullPage:true});
 await page.setViewportSize({width:1440,height:1000});
 // Obtain the actual persisted run ID instead of hardcoding a nonexistent route.
 const response=await page.request.get('http://127.0.0.1:8010/api/reconciliations?limit=100');const runs=(await response.json()).items;const run=runs.find(r=>r.id.startsWith('72cf969a'))||runs.find(r=>r.summary.lines===2&&r.status==='COMPLETED');
 if(!run)throw new Error('No persisted reviewed browser run found');
 await page.goto('http://127.0.0.1:3000/runs/'+run.id);
 await page.getByRole('button',{name:'Inspect',exact:true}).first().click();
 await expect(page.locator('.pdf-canvas p')).toHaveCount(0,{timeout:30000});
 await expect.poll(()=>page.locator('canvas').evaluateAll(cs=>cs.filter(c=>{const pixels=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let dark=0;for(let i=0;i<pixels.length;i+=4)if(pixels[i]<180&&pixels[i+1]<180&&pixels[i+2]<180&&pixels[i+3])dark++;return dark>100;}).length)).toBe(2);
 await page.screenshot({path:'../storage/browser-evidence.png',fullPage:true});
 if(errors.length)throw new Error(errors.join('\n'));console.log('Final dashboard chart, responsive layout and persisted PDF evidence verified.');await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
