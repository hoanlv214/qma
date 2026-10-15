import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

const backendTarget = process.env.VITE_BACKEND_URL || process.env.QMA_BACKEND_URL || "http://localhost:8000";
const gatewayTarget = process.env.VITE_GATEWAY_URL || process.env.QMA_ARC_GATEWAY_URL || "http://localhost:3000";

export default defineConfig({
  plugins: [react()],
      resolve: {
        alias: {
          "@": path.resolve(__dirname, "./src"),
        },
      },
      publicDir: "public",
      envDir: "..",
      envPrefix: ["VITE_", "QMA_"],
      server: {
        port: 5173,
        strictPort: false,
        fs: {
          allow: [".."],
        },
        proxy: {
          // Arc Gateway (port 3000) – must come BEFORE the catch-all /api rule
          "/api/balance": {
            target: gatewayTarget,
            changeOrigin: true,
          },
          "/api/wallet-status": {
            target: gatewayTarget,
            changeOrigin: true,
          },
          "/api/deposit-calldata": {
            target: gatewayTarget,
            changeOrigin: true,
          },
          "/api/withdraw": {
            target: gatewayTarget,
            changeOrigin: true,
          },
          "/qma-access": {
            target: gatewayTarget,
            changeOrigin: true,
          },
          "/health": {
            target: gatewayTarget,
            changeOrigin: true,
          },
          // FastAPI backend – catch-all for all other /api/* routes
          "/api": {
            target: backendTarget,
            changeOrigin: true,
          },
          "/openapi.json": {
            target: backendTarget,
            changeOrigin: true,
          },
          "/openapi/": {
            target: backendTarget,
            changeOrigin: true,
          },
        },
      },
  build: {
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor_react: ["react", "react-dom"],
          vendor_web3: ["viem", "wagmi", "@reown/appkit", "@reown/appkit-adapter-wagmi"],
        },
      },
    },
  },
  preview: {
    port: 4173,
  },
});
