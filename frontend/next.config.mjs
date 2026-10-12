/** @type {import('next').NextConfig} */
// Browser-side hardening. The CSP is ENFORCED: the Chromium e2e specs (chat stream, upload, dashboards with DuckDB-WASM and AG Grid, the
// admin console) pass with it on. If a new feature needs another source, add it to the matching directive below; to debug, rename the header
// to Content-Security-Policy-Report-Only and read the console.
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob:",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join('; ');

const securityHeaders = [
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=(), payment=()' },
  { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' }, // browsers ignore it over plain http
  { key: 'Content-Security-Policy', value: csp },
];

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [{ source: '/:path*', headers: securityHeaders }];
  },
  output: 'standalone', // self-contained server for the Docker runner stage
  async rewrites() {
    // `fallback`, not a plain array: a plain rewrite is checked BEFORE dynamic route handlers (app/api/conversations/[id]),
    // which would send those calls straight to the backend with only the login cookie and no Bearer header (401).
    // A fallback rewrite applies only when no route handler matched.
    return {
      fallback: [
        {
          source: '/api/:path*',
          destination: process.env.API_URL
            ? `${process.env.API_URL}/api/:path*`
            : 'http://backend:8000/api/:path*',
        },
      ],
    };
  },
  webpack: (config, { isServer, webpack }) => {
    config.experiments = {
      ...config.experiments,
      asyncWebAssembly: true,
      layers: true,
    };
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        https: false,
        http: false,
        stream: false,
        crypto: false,
        path: false,
        os: false,
      };
      config.plugins.push(
        new webpack.NormalModuleReplacementPlugin(/^node:/, (resource) => {
          resource.request = resource.request.replace(/^node:/, '');
        })
      );
    }
    return config;
  },
};

export default nextConfig;
