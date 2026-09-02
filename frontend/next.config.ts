import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Added rewrites to proxy all /api/* requests from the Next.js frontend to the FastAPI backend.
  // This ensures that the GitHub installation callback (and other APIs) are correctly routed to the backend.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: process.env.NEXT_PUBLIC_BACKEND_URL
          ? `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/:path*`
          : "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
