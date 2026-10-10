"use client";
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { clsx } from 'clsx';
import type { ReactNode, ButtonHTMLAttributes } from 'react';
export function Button({children,className,variant='primary',...props}:ButtonHTMLAttributes<HTMLButtonElement>&{variant?:'primary'|'secondary'|'danger'}) { return <button className={clsx('button',variant,className)} {...props}>{children}</button>; }
export function Badge({value}:{value:string}) { const good=['AUTO_APPROVABLE','COMPLETED','PASS','SAME_PRODUCT','NOT_APPLICABLE'].includes(value); const bad=['BLOCKED','FAILED','FAIL'].includes(value); return <span className={clsx('badge',good?'good':bad?'bad':'warning')}>{value.replaceAll('_',' ').toLowerCase()}</span>; }
export function Empty({title,description,children}:{title:string;description:string;children?:ReactNode}){return <div className="empty"><div className="empty-icon">+</div><h3>{title}</h3><p>{description}</p>{children}</div>;}
export function ErrorBox({error}:{error:unknown}){return error?<div role="alert" className="error-box">{error instanceof Error?error.message:String(error)}</div>:null;}
export function Modal({open,onClose,title,children}:{open:boolean;onClose:()=>void;title:string;children:ReactNode}) {return <Dialog.Root open={open} onOpenChange={v=>!v&&onClose()}><Dialog.Portal><Dialog.Overlay className="modal-overlay"/><Dialog.Content className="modal"><div className="modal-title"><Dialog.Title>{title}</Dialog.Title><Dialog.Close aria-label="Close"><X size={20}/></Dialog.Close></div><Dialog.Description className="sr-only">Inspect source documents and submit an audited correction.</Dialog.Description>{children}</Dialog.Content></Dialog.Portal></Dialog.Root>;}
