import {test,expect} from '@playwright/test';
import path from 'node:path';
test('actual PDF upload, SSE, evidence, reviewer recomputation, reports and persistence',async({page,request})=>{
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/new');
  await expect(page.getByRole('heading',{name:'New reconciliation',exact:true})).toBeVisible();
  await page.locator('input[type=file]').nth(0).setInputFiles(path.resolve('../storage/browser-fixtures/purchase_order.pdf'));
  await expect(page.getByRole('button',{name:'purchase_order.pdf',exact:true})).toBeVisible();
  await page.locator('input[type=file]').nth(0).setInputFiles(path.resolve('../storage/browser-fixtures/invoice.pdf'));
  await expect(page.getByRole('button',{name:'invoice.pdf',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Start reconciliation',exact:true}).click();
  await expect(page).toHaveURL(/\/runs\/[a-f0-9-]+/);
  await expect(page.locator('.run-actions .badge')).toHaveText('blocked',{timeout:450000});
  await expect(page.getByText('spec mismatch',{exact:true}).first()).toBeVisible();
  const runId=page.url().split('/').pop()!;
  const stream=await request.get(`/api/reconciliations/${runId}/stream`);
  expect(stream.ok()).toBeTruthy();expect(await stream.text()).toContain('event: settled');expect(await stream.text()).toContain('EXTRACTING');
  await page.screenshot({path:'../storage/browser-run.png',fullPage:true});
  await page.getByRole('button',{name:'Inspect',exact:true}).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect.poll(()=>page.locator('canvas').evaluateAll(cs=>cs.filter(c=>(c as HTMLCanvasElement).width>100&&(c as HTMLCanvasElement).height>100).length),{timeout:30000}).toBe(2);
  await expect(page.locator('.pdf-canvas p')).toHaveCount(0,{timeout:30000});
  await expect.poll(()=>page.locator('canvas').evaluateAll(cs=>cs.filter(c=>{const el=c as HTMLCanvasElement;const pixels=el.getContext('2d')!.getImageData(0,0,el.width,el.height).data;let dark=0;for(let i=0;i<pixels.length;i+=4){if(pixels[i]<200&&pixels[i+1]<200&&pixels[i+2]<200&&pixels[i+3]>0)dark++;}return dark>100;}).length)).toBe(2);
  await expect(page.getByText('Highlighted source: page 1').first()).toBeVisible();
  await page.screenshot({path:'../storage/browser-evidence.png',fullPage:true});
  await page.getByLabel('Review action').selectOption('substitution');
  await page.getByLabel('Evidence / review note').fill('QA reviewer: documented configuration substitution approved for this synthetic test.');
  await page.getByRole('button',{name:'Save & recompute'}).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(page.locator('.run-actions .badge')).toHaveText('auto approvable',{timeout:90000});
  await page.reload();
  await expect(page.getByText('QA reviewer: documented configuration substitution approved for this synthetic test.',{exact:false}).first()).toBeVisible();
  for(const label of ['PDF report','CSV','JSON']){
    const download=page.waitForEvent('download');await page.getByRole('button',{name:label,exact:true}).click();const file=await download;expect(await file.failure()).toBeNull();
  }
  for(const route of ['/','/runs','/review','/documents','/evaluation','/settings']){
    await page.goto(route);await expect(page.locator('h1')).toBeVisible();
  }
  await page.goto('/');await expect(page.locator('.stat-card strong').first()).toHaveText(/\d+/);await expect(page.locator('.recharts-sector').first()).toBeVisible();await page.screenshot({path:'../storage/browser-overview.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:'../storage/browser-mobile.png',fullPage:true});
  expect(errors).toEqual([]);
});
