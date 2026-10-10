export const dynamic='force-dynamic';
export const runtime='nodejs';
export async function GET(request:Request,{params}:{params:Promise<{id:string}>}){
 const {id}=await params;
 const url=new URL(request.url);
 const base=process.env.RECONCILE_API_ORIGIN||'http://127.0.0.1:8010';
 const headers=new Headers({Accept:'text/event-stream'});
 for(const name of ['authorization','last-event-id']){const value=request.headers.get(name);if(value)headers.set(name,value);}
 const upstream=await fetch(`${base}/api/reconciliations/${encodeURIComponent(id)}/stream${url.search}`,{headers,cache:'no-store',signal:request.signal});
 return new Response(upstream.body,{status:upstream.status,headers:{'Content-Type':upstream.headers.get('content-type')||'text/event-stream','Cache-Control':'no-cache, no-transform','X-Accel-Buffering':'no'}});
}
