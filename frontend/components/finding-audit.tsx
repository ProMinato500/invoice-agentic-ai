"use client";
import {useQuery} from '@tanstack/react-query';
import {api} from '@/lib/api';
import type {Doc,Evidence} from '@/lib/types';
import {Badge,ErrorBox} from './ui';
import PdfViewer from './pdf-viewer';

type Audit={finding:{code:string;message:string;severity:string};source_evidence:Evidence[];documents:Doc[];run_version:number;citation_status:string;resolution:string};
export default function FindingAudit({findingId,onLoaded}:{findingId:string;onLoaded:()=>void}){
 const query=useQuery({queryKey:['finding-audit',findingId],queryFn:async()=>{const result=await api<Audit>(`/discrepancies/${findingId}/investigate`,{method:'POST'});onLoaded();return result;},retry:false,refetchOnWindowFocus:false});
 const data=query.data;
 return <div className="execution-trace finding-audit"><ErrorBox error={query.error}/>{query.isLoading&&<p role="status">Looking up saved source evidence...</p>}{data&&<><div className="trace-heading"><Badge value={data.finding.severity}/><strong>{data.finding.code.replaceAll('_',' ').toLowerCase()}</strong><span>Result version {data.run_version}</span></div><p>{data.finding.message}</p><p className="source-note">{data.resolution}</p>{data.citation_status==='NO_SPECIFIC_SOURCE_CITATION'&&<p role="status" className="source-note">No specific source citation was attached to this finding. Showing the original documents without highlights. This finding needs source verification.</p>}<div className="evidence-grid">{data.documents.map(d=>{const evidence=data.source_evidence.filter(e=>e.document_id===d.id&&e.bbox?.length===4);return <div key={d.id}><PdfViewer documentId={d.id} evidence={evidence} title={`${d.kind.toUpperCase()}: ${d.name}`}/>{!evidence.length&&<p className="source-note">No linked source region for this document. Use the page controls to inspect it.</p>}</div>;})}</div><details className="finding-audit-details"><summary>Lookup result and extracted document metadata</summary><pre className="trace-json">{JSON.stringify(data,null,2)}</pre></details></>}</div>;
}
