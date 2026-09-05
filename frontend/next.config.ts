import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // We use Next.js rewrites to proxy specific API routes from the frontend
  // directly to our FastAPI backend. This avoids CORS issues and keeps the
  // frontend interacting with a single origin (localhost:3000).
  async rewrites() {
    return [
      // 1. Proxy GitHub repository fetching and selection routes
      {
        source: "/api/github/repositories/:path*",
        destination: process.env.NEXT_PUBLIC_BACKEND_URL
          ? `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/github/repositories/:path*`
          : "http://127.0.0.1:8000/api/github/repositories/:path*",
      },
      // 2. Proxy the repository scanning and analysis routes

      {
        source: "/api/github/scan/:path*",
        destination: process.env.NEXT_PUBLIC_BACKEND_URL
          ? `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/github/scan/:path*`
          : "http://127.0.0.1:8000/api/github/scan/:path*",
      },
      // 3. Proxy the chat interface
      {
        source: "/api/github/chat",
        destination: process.env.NEXT_PUBLIC_BACKEND_URL
          ? `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/github/chat`
          : "http://127.0.0.1:8000/api/github/chat",
      },
      // 4. Proxy the fix generator (simple + agentic pipeline)
      {
        source: "/api/github/fix/:path*",
        destination: process.env.NEXT_PUBLIC_BACKEND_URL
          ? `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/github/fix/:path*`
          : "http://127.0.0.1:8000/api/github/fix/:path*",
      },
    ];
  },
};

export default nextConfig;
