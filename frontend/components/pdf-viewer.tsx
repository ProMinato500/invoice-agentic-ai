"use client";
import {useEffect,useRef,useState} from 'react';
import {ChevronLeft,ChevronRight,ZoomIn,ZoomOut} from 'lucide-react';
import {token} from '@/lib/api';
import type {Evidence} from '@/lib/types';
import {Button,ErrorBox} from './ui';
export default function PdfViewer({documentId,evidence=[],title}:{documentId:string;evidence?:Evidence[];title:string}) {
  const canvas=useRef<HTMLCanvasElement>(null);const taskRef=useRef<{destroy:()=>Promise<void>}|null>(null);
  const [page,setPage]=useState(evidence[0]?.page||1);const [count,setCount]=useState(1);const [zoom,setZoom]=useState(.8);const [error,setError]=useState<unknown>(null);const [loading,setLoading]=useState(true);
  useEffect(()=>{if(evidence[0])setPage(evidence[0].page);},[evidence]);
  useEffect(()=>{let cancelled=false;let rendering:{cancel:()=>void}|null=null;setLoading(true);setError(null);
    async function render(){try{const pdfjs=await import('pdfjs-dist');pdfjs.GlobalWorkerOptions.workerSrc='/pdf.worker.min.mjs';const task=pdfjs.getDocument({url:`/api/documents/${documentId}/file`,httpHeaders:token()?{Authorization:`Bearer ${token()}`}:{}});taskRef.current=task;const pdf=await task.promise;if(cancelled){await task.destroy();return;}setCount(pdf.numPages);const p=await pdf.getPage(Math.min(page,pdf.numPages));const viewport=p.getViewport({scale:zoom});const el=canvas.current;if(!el||cancelled)return;el.width=viewport.width;el.height=viewport.height;const context=el.getContext('2d')!;const rt=p.render({canvasContext:context,viewport,canvas:el});rendering=rt;await rt.promise;if(cancelled)return;context.fillStyle='rgba(245,158,11,.19)';context.strokeStyle='#dc8b05';context.lineWidth=2;for(const e of evidence.filter(x=>x.page===page)){const r=viewport.convertToViewportRectangle([e.bbox[0],p.view[3]-e.bbox[1],e.bbox[2],p.view[3]-e.bbox[3]]);const x=Math.min(r[0],r[2]),y=Math.min(r[1],r[3]);context.fillRect(x,y,Math.abs(r[2]-r[0]),Math.abs(r[3]-r[1]));context.strokeRect(x,y,Math.abs(r[2]-r[0]),Math.abs(r[3]-r[1]));}setLoading(false);}catch(e){if(!cancelled){setError(e);setLoading(false);}}}
    render();return()=>{cancelled=true;rendering?.cancel();taskRef.current?.destroy().catch(()=>{});};
  },[documentId,page,zoom,evidence]);
  return <section className="pdf-viewer"><div className="pdf-toolbar"><strong>{title}</strong><div><Button variant="secondary" aria-label="Previous PDF page" disabled={page<=1} onClick={()=>setPage(page-1)}><ChevronLeft size={15}/></Button><span>{page} / {count}</span><Button variant="secondary" aria-label="Next PDF page" disabled={page>=count} onClick={()=>setPage(page+1)}><ChevronRight size={15}/></Button><Button variant="secondary" aria-label="Zoom out" onClick={()=>setZoom(Math.max(.4,zoom-.2))}><ZoomOut size={15}/></Button><Button variant="secondary" aria-label="Zoom in" onClick={()=>setZoom(Math.min(2,zoom+.2))}><ZoomIn size={15}/></Button></div></div><ErrorBox error={error}/><div className="pdf-canvas">{loading&&<p className="muted">Rendering original PDF...</p>}<canvas ref={canvas}/></div>{evidence.length>0&&<div className="source-caption">Highlighted source: page {evidence[0].page}<br/>{evidence[0].raw_text}</div>}</section>;
}
