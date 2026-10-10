export function token() { return typeof window !== 'undefined' ? sessionStorage.getItem('reconcile_token') || '' : ''; }
export async function api<T>(path:string, options:RequestInit={}):Promise<T> {
  const headers = new Headers(options.headers);
  if (token()) headers.set('Authorization',`Bearer ${token()}`);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type','application/json');
  const response = await fetch(`/api${path}`,{...options,headers});
  if (!response.ok) { let message=`Request failed (${response.status})`; try { const data=await response.json(); message=typeof data.detail==='string'?data.detail:JSON.stringify(data.detail); } catch {} throw new Error(message); }
  return response.json();
}
export async function download(path:string,name:string) {
  const response=await fetch(`/api${path}`,{headers:token()?{Authorization:`Bearer ${token()}`}:{}});
  if(!response.ok) throw new Error('Download is not available yet');
  const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url);
}
