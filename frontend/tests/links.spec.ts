import {test,expect} from '@playwright/test';
test('linked item evidence opens the correct PO page and invoice page',async({page,request})=>{
 const listed=await(await request.get('/api/reconciliations?limit=100')).json();
 let target:{run:string;sku:string;poPage:number;invoicePage:number}|null=null;
 for(const r of listed.items){
  const matches=await(await request.get(`/api/reconciliations/${r.id}/matches?limit=100`)).json();
  const line=matches.items?.find((m:{po_line?:{evidence:{page:number}[]};invoice_line:{sku:string;evidence:{page:number}[]}})=>(m.po_line?.evidence?.[0]?.page??0)>1&&m.invoice_line.evidence?.length);
  if(line){target={run:r.id,sku:line.invoice_line.sku,poPage:line.po_line.evidence[0].page,invoicePage:line.invoice_line.evidence[0].page};break;}
 }
 expect(target).toBeTruthy();await page.goto(`/runs/${target!.run}`);
 await page.locator('.results-table tbody tr').filter({hasText:target!.sku}).getByRole('button',{name:'Inspect',exact:true}).click();
 await expect(page.getByRole('dialog')).toBeVisible();
 const viewers=page.locator('.evidence-grid .pdf-viewer');
 await expect(viewers).toHaveCount(2);
 await expect(viewers.nth(0).locator('.source-caption')).toContainText(`Highlighted source: page ${target!.poPage}`);
 await expect(viewers.nth(1).locator('.source-caption')).toContainText(`Highlighted source: page ${target!.invoicePage}`);
 await expect(page.locator('.pdf-canvas p')).toHaveCount(0,{timeout:30000});
 await expect.poll(()=>page.locator('.evidence-grid canvas').evaluateAll(cs=>cs.filter(c=>{const el=c as HTMLCanvasElement;const p=el.getContext('2d')!.getImageData(0,0,el.width,el.height).data;let orange=0;for(let i=0;i<p.length;i+=4)if(p[i]>180&&p[i+1]>90&&p[i+1]<220&&p[i+2]<100)orange++;return orange>20;}).length)).toBe(2);
 await page.screenshot({path:'../storage/browser-linked-items.png',fullPage:true});
});
