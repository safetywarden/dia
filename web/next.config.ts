import type { NextConfig } from "next";

const config: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Frame-Options", value: "DENY" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        // Contact data is personal data: keep it out of shared caches and search.
        { key: "X-Robots-Tag", value: "noindex, nofollow" },
      ],
    }];
  },
};

export default config;
