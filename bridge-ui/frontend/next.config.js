/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    BRIDGE_API_URL: process.env.BRIDGE_API_URL || "http://localhost:8000",
  },
  // The firewall console is the primary screen: serve /console at the root "/"
  // (the URL stays "/"). `beforeFiles` runs BEFORE the filesystem route app/page.tsx
  // (the legacy app), which still exists as a file but stops serving "/".
  // To revert: remove this block. (The legacy app is also re-exposed at /legacy.)
  async rewrites() {
    return {
      beforeFiles: [{ source: "/", destination: "/console" }],
    };
  },
};

module.exports = nextConfig;
