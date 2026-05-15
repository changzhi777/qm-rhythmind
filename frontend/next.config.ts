import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  basePath: "/qm",
  output: "export",
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
