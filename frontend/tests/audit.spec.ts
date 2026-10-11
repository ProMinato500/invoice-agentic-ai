import {test,expect} from '@playwright/test';
test('finding source lookup opens visible evidence, metadata and inline request errors',async({page,request})=>{
 const runs=await(await request.get('/api/reconciliations?limit=100')).json();
 let target:{run:string;code:string}|null=null;
 for(const r of runs.items){if(['PROCESSING','QUEUED'].includes(r.status))continue;const fs=await(await request.get(`/api/reconciliations/${r.id}/discrepancies`)).json();const f=fs.items.find((f:{match_id:string|null})=>f.match_id);if(f){target={run:r.id,code:f.code};break;}}
 expect(target).toBeTruthy();await page.goto(`/runs/${target!.run}`);
 const finding=page.locator('.finding').filter({hasText:target!.code.replaceAll('_',' ').toLowerCase()}).first();
 await finding.locator('summary').click();await finding.getByRole('button',{name:'Audit source lookup'}).click();
 const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();
 await expect(dialog.getByText('Finding source audit',{exact:true})).toBeVisible();
 await expect(dialog.locator('.finding-audit .pdf-viewer')).toHaveCount(2,{timeout:30000});
 await expect(dialog.locator('.source-caption').first()).toBeVisible();
 await expect(dialog.locator('.pdf-canvas p')).toHaveCount(0,{timeout:30000});
 await dialog.getByText('Lookup result and extracted document metadata').click();
 await expect(dialog.locator('.trace-json')).toContainText('SOURCE_CITATIONS_AVAILABLE');
 await page.screenshot({path:'../storage/browser-finding-audit.png',fullPage:true});
 await dialog.getByRole('button',{name:'Close',exact:true}).click();
 await page.route('**/api/discrepancies/*/investigate',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Source lookup temporarily unavailable'})}));
 await finding.getByRole('button',{name:'Audit source lookup'}).click();
 await expect(page.getByRole('dialog').getByText(/Source lookup temporarily unavailable/)).toBeVisible();
});
