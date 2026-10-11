import {test,expect} from '@playwright/test';
test('reconstructed tables preserve headers and highlight clicked source cells',async({page,request})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const listed=await(await request.get('/api/reconciliations?limit=100')).json();
 let selected:{run:string;document:string;name:string;tables:{id:string;type_hint:string;cells:{evidence_ids:string[];bbox:number[]|null;page:number}[]}[]}|null=null;
 for(const r of listed.items){
  if(['PROCESSING','QUEUED'].includes(r.status))continue;
  const detail=await(await request.get(`/api/reconciliations/${r.id}`)).json();
  for(const d of detail.documents??[]){
   const extraction=await(await request.get(`/api/documents/${d.id}/tables`)).json();
   if(extraction.tables?.some((t:{cells:{evidence_ids:string[];bbox:number[]|null}[]})=>t.cells.some(c=>c.evidence_ids.length&&c.bbox))){selected={run:r.id,document:d.id,name:d.name,tables:extraction.tables};break;}
  }
  if(selected)break;
 }
 expect(selected).toBeTruthy();
 await page.goto(`/runs/${selected!.run}`);
 await page.locator('.source-document').filter({hasText:selected!.name}).getByRole('button',{name:'Inspect OCR & extraction'}).click();
 await page.getByRole('button',{name:'tables',exact:true}).click();
 await expect(page.getByLabel('Source table')).toBeVisible({timeout:30000});
 await expect(page.locator('.source-table thead th').first()).toBeVisible();
 const delivery=selected!.tables.find(t=>t.type_hint==='delivery_schedule');
 if(delivery)await page.getByLabel('Source table').selectOption(delivery.id);
 const cell=page.locator('.source-table tbody button:enabled').first();
 await cell.click();await expect(page.locator('.source-table button.selected')).toHaveCount(1);
 await expect(page.getByText(/Highlighted source: page/)).toBeVisible();
 await expect(page.locator('.pdf-canvas p')).toHaveCount(0,{timeout:30000});
 await expect.poll(()=>page.locator('canvas').evaluateAll(cs=>cs.filter(c=>{const el=c as HTMLCanvasElement;const p=el.getContext('2d')!.getImageData(0,0,el.width,el.height).data;let dark=0;for(let i=0;i<p.length;i+=4)if(p[i]<200&&p[i+1]<200&&p[i+2]<200&&p[i+3])dark++;return dark>100;}).length)).toBeGreaterThan(0);
 await page.screenshot({path:'../storage/browser-table-trace.png',fullPage:true});
 if(selected!.tables.length>1){await page.getByLabel('Source table').selectOption({index:1});await expect(page.locator('.source-table button.selected')).toHaveCount(0);}
 expect(errors).toEqual([]);
});
