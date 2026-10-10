"use client";
import { useState } from 'react';
import { QueryClient,QueryClientProvider } from '@tanstack/react-query';
export default function Providers({children}:{children:React.ReactNode}) {const [client]=useState(()=>new QueryClient({defaultOptions:{queries:{retry:1,staleTime:3000}}}));return <QueryClientProvider client={client}>{children}</QueryClientProvider>;}
