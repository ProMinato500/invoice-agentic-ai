import type { NextConfig } from 'next';
const config: NextConfig = {
  async rewrites() { return [{ source: '/api/:path*', destination: `${process.env.RECONCILE_API_ORIGIN || 'http://127.0.0.1:8010'}/api/:path*` }]; },
};
export default config;
