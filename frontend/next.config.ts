import type { NextConfig } from 'next';
const config: NextConfig = {
  compress: false,
  async rewrites() { return [{ source: '/api/:path*', destination: `${process.env.RECONCILE_API_ORIGIN || 'http://127.0.0.1:8010'}/api/:path*` }]; },
};
export default config;
