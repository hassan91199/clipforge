import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // No SSR/API routes/middleware in this app - everything is client-side,
  // calling the FastAPI backend directly (NEXT_PUBLIC_API_URL). Static
  // export lets it be hosted on plain S3 + CloudFront (CF-34).
  output: "export",
};

export default nextConfig;
