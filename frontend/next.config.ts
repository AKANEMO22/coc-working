import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    // The separate CV product is removed; old bookmarks lead to interview setup.
    return [{ source: "/cv-lab", destination: "/interview", permanent: true }];
  },
};

export default nextConfig;
