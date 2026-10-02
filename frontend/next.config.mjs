/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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
